"""
Torri Scheduler - Main orchestration service.

Responsibilities:
- Load configuration from torii.conf
- Load and validate YAML configuration files (pipelines, projects, jobs)
- Create configuration objects
- Listen for VCS events on Kafka
- Route changes through pipelines
- Execute jobs
- Submit to VCS on success

Design: Driver-based architecture supporting multiple VCS systems (Gerrit, GitHub, GitLab, etc.)
Adding new VCS support requires only new driver implementations, no changes to core scheduler.
"""

import sys
import json
import time
from typing import Optional, Dict, Any, Tuple

from shared.logger_setup import get_logger
from torri.config.config_manager import ConfigurationManager
from torri.scheduler import (
    PipelineConfigLoader,
    PipelineEntryGate,
    UnifiedRefPipelineManager,
    MergerCoordinator,
    GateAlgorithm,
    TorriRedis,
)
from torri.gerrit import GerritRestConnection
from torri.drivers import DriverFactory
from torri.drivers.base_drivers import (
    ChangeSource,
    ValidationGate,
    MergeDriver,
    SyntheticRefProvider,
)


logger = None


def initialize_logging(config: ConfigurationManager):
    """Initialize logging using config."""
    global logger
    logger = get_logger('torri.scheduler')


def load_configurations(config: ConfigurationManager) -> Tuple[Dict[str, Any], bool]:
    """
    Load and validate all configuration files.
    
    Returns:
        (config_objects_dict, success_bool)
    """
    logger.info("Loading configuration files...")
    
    try:
        # Validate files exist
        if not config.validate_files_exist():
            logger.error("Some configuration files not found")
            return {}, False
        
        # Load pipelines
        logger.info(f"Loading pipelines from {config.pipelines_yaml_path}")
        pipeline_loader = PipelineConfigLoader(config.pipelines_yaml_path)
        pipelines = pipeline_loader.get_all_pipelines()
        
        if not pipelines:
            logger.error("No pipelines loaded")
            return {}, False
        
        logger.info(f"Loaded {len(pipelines)} pipelines: {list(pipelines.keys())}")
        
        # Load projects
        import yaml
        logger.info(f"Loading projects from {config.projects_yaml_path}")
        with open(config.projects_yaml_path, 'r') as f:
            projects_data = yaml.safe_load(f) or {}
        projects = projects_data.get('projects', [])
        logger.info(f"Loaded {len(projects)} projects")
        
        # Load jobs
        logger.info(f"Loading jobs from {config.jobs_yaml_path}")
        with open(config.jobs_yaml_path, 'r') as f:
            jobs_data = yaml.safe_load(f) or {}
        jobs = jobs_data.get('jobs', [])
        logger.info(f"Loaded {len(jobs)} jobs")
        
        config_objects = {
            'pipeline_loader': pipeline_loader,
            'pipelines': pipelines,
            'projects': projects,
            'jobs': jobs,
        }
        
        logger.info("All configuration files loaded successfully")
        return config_objects, True
    
    except Exception as e:
        logger.error(f"Failed to load configurations: {e}", exc_info=True)
        return {}, False


def initialize_connections(config: ConfigurationManager) -> Tuple[Dict[str, Any], bool]:
    """
    Initialize connections to external services.
    
    Returns:
        (connections_dict, success_bool)
    """
    logger.info("Initializing external connections...")
    
    try:
        # Gerrit connection (used internally by drivers and validators)
        logger.info(f"Connecting to Gerrit at {config.gerrit_server}:{config.gerrit_rest_port}")
        gerrit_conn = GerritRestConnection(
            gerrit_server=config.gerrit_server,
            gerrit_user=config.gerrit_user,
            gerrit_password=config.gerrit_password,
            gerrit_account_id=None,
            rest_port=config.gerrit_rest_port,
            use_https=config.gerrit_rest_https,
        )
        logger.info("Gerrit connection established")
        
        # Redis connection
        logger.info(f"Connecting to Redis at {config.redis_host}:{config.redis_port}")
        redis_conn = TorriRedis(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            password=config.redis_password,
        )
        logger.info("Redis connection established")
        
        connections = {
            'gerrit': gerrit_conn,
            'redis': redis_conn,
        }
        
        logger.info("All connections established")
        return connections, True
    
    except Exception as e:
        logger.error(f"Failed to initialize connections: {e}", exc_info=True)
        return {}, False


def initialize_components(
    config: ConfigurationManager,
    config_objects: Dict[str, Any],
    connections: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    """
    Initialize scheduler components.
    
    Returns:
        (components_dict, success_bool)
    """
    logger.info("Initializing scheduler components...")
    
    try:
        gerrit_conn = connections['gerrit']
        redis_conn = connections['redis']
        pipeline_loader = config_objects['pipeline_loader']
        
        # Pipeline entry gate
        logger.info("Initializing pipeline entry gate")
        entry_gate = PipelineEntryGate(gerrit_conn, pipeline_loader)
        
        # Merger coordinator
        logger.info("Initializing merger coordinator")
        merger_coordinator = MergerCoordinator(
            kafka_servers=config.kafka_bootstrap_servers_list,
            requests_topic=config.kafka_topic_merger_requests,
            responses_topic=config.kafka_topic_merger_responses,
            consumer_group=config.kafka_group_scheduler,
        )
        
        # Unified ref pipeline manager
        logger.info("Initializing ref pipeline manager")
        ref_manager = UnifiedRefPipelineManager(
            redis_conn,
            gerrit_conn,
            merger_coordinator,
        )
        
        # Gate algorithm
        logger.info("Initializing gate algorithm")
        gate_algo = GateAlgorithm(gerrit_conn, ref_manager)
        
        components = {
            'entry_gate': entry_gate,
            'merger_coordinator': merger_coordinator,
            'ref_manager': ref_manager,
            'gate_algo': gate_algo,
        }
        
        logger.info("All components initialized")
        return components, True
    
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}", exc_info=True)
        return {}, False


def initialize_drivers(
    config: ConfigurationManager,
    components: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    """
    Initialize VCS drivers based on configuration.
    
    Returns:
        (drivers_dict, success_bool)
        
    Drivers provide abstraction over specific VCS systems (Gerrit, GitHub, etc.)
    New VCS support can be added without modifying core scheduler code.
    """
    logger.info("Initializing VCS drivers...")
    
    try:
        driver_type = config.scheduler_driver
        logger.info(f"Using driver: {driver_type}")
        
        # Validate driver is supported
        if not DriverFactory.validate_driver_type(driver_type):
            supported = DriverFactory.get_supported_drivers()
            logger.error(f"Unsupported driver: {driver_type}. Supported: {supported}")
            return {}, False
        
        # Create driver instances
        success, drivers = DriverFactory.create_drivers(
            driver_type,
            config,
            components
        )
        
        if not success:
            logger.error(f"Failed to create {driver_type} drivers")
            return {}, False
        
        logger.info(f"Drivers for {driver_type} initialized successfully")
        return drivers, True
    
    except Exception as e:
        logger.error(f"Failed to initialize drivers: {e}", exc_info=True)
        return {}, False


def validate_change_in_pipeline(
    change_number: str,
    patchset: str,
    pipeline_name: str,
    validation_gate: ValidationGate
) -> Tuple[bool, str]:
    """
    Check if change can enter pipeline using VCS validation rules.
    
    Returns:
        (can_enter: bool, message: str)
    """
    logger.info(f"Validating change {change_number} for {pipeline_name} pipeline")
    
    can_enter, message = validation_gate.can_enter_pipeline(
        change_number,
        patchset,
        pipeline_name
    )
    
    if can_enter:
        logger.info(f"Change {change_number} allowed in {pipeline_name} pipeline")
    else:
        logger.warning(f"Change {change_number} rejected from {pipeline_name}: {message}")
    
    return can_enter, message



def execute_pipeline_jobs(
    change_number: str,
    patchset: str,
    pipeline_name: str,
    jobs: list
) -> Tuple[str, str]:
    """
    Execute jobs for pipeline.
    
    MOCKED: Returns success for now. Will be implemented later with actual job execution.
    
    Returns:
        (status: 'SUCCESS'|'FAILED', reason: str)
    """
    logger.info(f"Executing {pipeline_name} pipeline jobs for change {change_number}")
    
    # MOCKED JOB EXECUTION
    # In real implementation, this will:
    # 1. Get jobs for pipeline from config
    # 2. Execute each job
    # 3. Collect results
    # 4. Return status
    
    # For now, always succeed
    logger.info(f"MOCKED: {pipeline_name} pipeline jobs succeeded for change {change_number}")
    return 'SUCCESS', 'Mocked job execution'


def submit_to_vcs(
    change_number: str,
    merge_driver: MergeDriver
) -> Tuple[bool, str]:
    """
    Submit change to VCS (Gerrit, GitHub, etc.) using driver.
    
    Returns:
        (success: bool, message: str)
    """
    logger.info(f"Submitting change {change_number} to VCS")
    
    try:
        success, response = merge_driver.submit_change(change_number)
        
        if success:
            status = response.get('status')
            message = response.get('message', f"Merged with status {status}")
            logger.info(f"Change {change_number} submitted successfully. {message}")
            return True, message
        else:
            error = response.get('message', str(response))
            logger.error(f"Failed to submit change {change_number}: {error}")
            return False, error
    
    except Exception as e:
        logger.error(f"Error submitting change {change_number}: {e}", exc_info=True)
        return False, str(e)


def process_change(
    change_number: str,
    patchset: str,
    config_objects: Dict[str, Any],
    components: Dict[str, Any],
    drivers: Dict[str, Any],
    connections: Dict[str, Any]
) -> bool:
    """
    Process single change through scheduler pipeline using VCS drivers.
    
    Flow:
    1. Check if can enter check pipeline (validation_gate driver)
    2. Enqueue change
    3. Get synthetic ref (synthetic_ref_provider driver)
    4. Execute check pipeline jobs
    5. Check if can enter gate pipeline
    6. Submit to VCS (merge_driver)
    7. Update state
    
    Returns:
        bool: Success status
    """
    logger.info("=" * 60)
    logger.info(f"Processing change {change_number} patchset {patchset}")
    logger.info("=" * 60)
    
    change_id = str(change_number)
    ps = str(patchset)
    
    validation_gate = drivers['validation_gate']
    synthetic_ref_provider = drivers['synthetic_ref_provider']
    merge_driver = drivers['merge_driver']
    
    ref_manager = components['ref_manager']
    jobs = config_objects['jobs']
    
    try:
        # Step 1: Check pipeline entry
        logger.info("Step 1: Validating change for check pipeline")
        can_enter_check, msg = validate_change_in_pipeline(
            change_id, ps, 'check', validation_gate
        )
        
        if not can_enter_check:
            logger.info(f"Change {change_id} cannot enter check pipeline. Stopping.")
            return False
        
        # Step 2: Enqueue change
        logger.info("Step 2: Enqueueing change")
        ref_manager.enqueue_change(change_id)
        
        # Step 3: Get synthetic ref
        logger.info("Step 3: Getting synthetic ref")
        success, synthetic_ref = synthetic_ref_provider.create_synthetic_ref(change_id)
        
        if not success:
            logger.error("Failed to get synthetic ref. Stopping.")
            return False
        
        # Step 4: Execute check pipeline
        logger.info("Step 4: Executing check pipeline jobs")
        status, reason = execute_pipeline_jobs(change_id, ps, 'check', jobs)
        
        # Update state
        ref_manager.update_pipeline_state(change_id, 'check', status)
        
        if status != 'SUCCESS':
            logger.info(f"Check pipeline failed: {reason}")
            return False
        
        logger.info("Check pipeline succeeded")
        
        # Step 5: Gate pipeline entry
        logger.info("Step 5: Validating change for gate pipeline")
        can_enter_gate, msg = validate_change_in_pipeline(
            change_id, ps, 'gate', validation_gate
        )
        
        if not can_enter_gate:
            logger.info(f"Change {change_id} cannot enter gate pipeline. Stopping.")
            return False
        
        # Step 6: Submit to VCS
        logger.info("Step 6: Submitting change to VCS")
        success, message = submit_to_vcs(change_id, merge_driver)
        
        # Update state
        gate_status = 'SUCCESS' if success else 'FAILED'
        ref_manager.update_pipeline_state(change_id, 'gate', gate_status)
        
        if not success:
            logger.error(f"Failed to submit change: {message}")
            return False
        
        logger.info(f"Change {change_id} successfully merged. Message: {message}")
        
        logger.info("=" * 60)
        logger.info(f"Change {change_id} processing COMPLETE")
        logger.info("=" * 60)
        
        return True
    
    except Exception as e:
        logger.error(f"Error processing change {change_id}: {e}", exc_info=True)
        return False


def process_vcs_event(
    event_data: Dict[str, Any],
    config_objects: Dict[str, Any],
    components: Dict[str, Any],
    drivers: Dict[str, Any],
    connections: Dict[str, Any]
):
    """
    Process VCS event from Kafka using driver abstraction.
    
    Parses event using ChangeSource driver (Gerrit, GitHub, etc.)
    Then processes change through pipeline.
    """
    try:
        change_source = drivers['change_source']
        
        # Parse event using VCS-specific driver
        logger.info("Parsing VCS event")
        success, parsed_data = change_source.parse_event(event_data)
        
        if not success:
            logger.warning(f"Failed to parse event: {parsed_data.get('error')}")
            return
        
        # Extract parsed change info
        change_number = parsed_data.get('change_id')
        patchset = parsed_data.get('patchset')
        event_type = parsed_data.get('event_type')
        
        logger.info(f"Received {event_type} event for change {change_number} patchset {patchset}")
        
        # Process only patchset-created events
        if event_type != 'patchset-created':
            logger.debug(f"Ignoring event type: {event_type}")
            return
        
        # Process change
        process_change(
            change_number,
            patchset,
            config_objects,
            components,
            drivers,
            connections
        )
    
    except Exception as e:
        logger.error(f"Error processing VCS event: {e}", exc_info=True)


def run_scheduler(config_file: Optional[str] = None):
    """
    Main scheduler orchestration.
    
    Startup sequence:
    1. Load configuration
    2. Load YAML files
    3. Initialize connections
    4. Initialize components
    5. Initialize VCS drivers
    6. Main event loop (listen for Kafka messages)
    """
    # Step 1: Load config
    logger.info("Step 1: Loading configuration from torii.conf")
    try:
        config = ConfigurationManager(config_file)
        logger.info(f"Configuration loaded from: {config.config_file}")
    except FileNotFoundError as e:
        logger.error(f"Configuration file not found: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}", exc_info=True)
        return False
    
    # Step 2: Load YAML files
    logger.info("Step 2: Loading and validating YAML configuration files")
    config_objects, success = load_configurations(config)
    if not success:
        return False
    
    # Step 3: Initialize connections
    logger.info("Step 3: Initializing external connections")
    connections, success = initialize_connections(config)
    if not success:
        return False
    
    # Step 4: Initialize components
    logger.info("Step 4: Initializing scheduler components")
    components, success = initialize_components(config, config_objects, connections)
    if not success:
        return False
    
    # Step 5: Initialize VCS drivers
    logger.info("Step 5: Initializing VCS drivers")
    drivers, success = initialize_drivers(config, components)
    if not success:
        return False
    
    # Step 6: Main event loop
    logger.info("Step 6: Starting main event loop")
    logger.info(f"Listening for VCS events on Kafka topic: {config.kafka_topic_gerrit_events}")
    logger.info(f"Using driver: {config.scheduler_driver}")
    
    try:
        # For testing, we can inject events manually or read from Kafka
        # In production, this will be a continuous loop reading from Kafka
        
        # PLACEHOLDER: Main event loop
        # This will be implemented to read from Kafka consumer
        # For now, we're ready to process events
        
        logger.info("Scheduler ready to process events")
        logger.info("Event processing will be implemented with Kafka consumer")
        
        # Keep service running
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        logger.info("Scheduler interrupted by user")
        return True
    except Exception as e:
        logger.error(f"Error in main event loop: {e}", exc_info=True)
        return False


def main():
    """
    Main entry point.
    
    Usage:
        python -m torri.scheduler.scheduler [config_file]
    """
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    
    # Initialize logging
    try:
        config = ConfigurationManager(config_file)
        initialize_logging(config)
    except:
        # Fallback logging if config not found
        logger = get_logger('torri.scheduler')
    
    logger.info("Starting Torri Scheduler Service")
    logger.info("=" * 60)
    
    success = run_scheduler(config_file)
    
    if success:
        logger.info("Scheduler shutdown cleanly")
        return 0
    else:
        logger.error("Scheduler failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())
