from . import TorriCLI
import os
import time
import threading
import yaml
from pathlib import Path

import voluptuous as V

from shared.logger_setup import get_logger, setup_logging
from shared.layout_validator import Validator
from torri.config.config_manager import ConfigurationManager
from torri.kafka.kafka_client import KafkaConnection
from torri.gerrit.gerritconnection import GerritEventProcessor, GerritRestConnection
from torri.gerrit.gerritsource import GerritSource
from torri.scheduler.redis_client import TorriRedis
from torri.scheduler.scheduler_queue import SchedulerQueue
from torri.scheduler.result_consumer import ResultConsumer


def _validate_yaml_files(yaml_dir: str, logger):
    """Validate all YAML files before starting. Raises on bad config."""
    logger.info("Validating YAML configuration files in %s", yaml_dir)

    nodesets_data = _load_yaml(yaml_dir, "nodesets.yaml")
    nodesets_data, nodeset_names = Validator.validate(nodesets_data, "nodesets.yaml")

    jobs_data = _load_yaml(yaml_dir, "jobs.yaml")
    jobs_data, job_names = Validator.validate(jobs_data, "jobs.yaml", list_of_nodesets=nodeset_names)

    pipelines_data = _load_yaml(yaml_dir, "pipelines.yaml")
    pipelines_data, pipeline_names = Validator.validate(pipelines_data, "pipelines.yaml")

    projects_data = _load_yaml(yaml_dir, "projects.yaml")
    Validator.validate(
        projects_data, "projects.yaml",
        list_of_pipelines=pipeline_names,
        list_of_jobs=job_names,
    )

    logger.info(
        "YAML validation passed: %d jobs, %d pipelines, %d projects",
        len(job_names), len(pipeline_names),
        len(projects_data.get("projects", [])),
    )


def _load_yaml(yaml_dir: str, filename: str) -> dict:
    path = os.path.join(yaml_dir, filename)
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def main():
    cli = TorriCLI("Torii Scheduler")
    args = cli.parse_args()

    # Setup logging using shared config from /app/config/log/
    log_config = Path("/app/config/log/main_logging.yaml")
    
    # Resolve log paths relative to scheduler workspace (container /app)
    # This allows ephemeral/logs/server-debug.log to resolve correctly
    workspace_root = Path(os.getenv("SCHEDULER_WORKSPACE_PATH", "/app"))
    setup_logging(log_config, workspace_root)

    logger = get_logger("torri.scheduler.main")
    logger.info("Starting Torii Scheduler")

    config = ConfigurationManager()

    # Resolve yaml_dir relative to torii.conf location so relative paths work
    yaml_dir = config.scheduler_config_dir
    if not os.path.isabs(yaml_dir):
        yaml_dir = os.path.join(os.path.dirname(config.config_file), yaml_dir)
    logger.info("Loading YAML config from %s", yaml_dir)

    try:
        _validate_yaml_files(yaml_dir, logger)
    except V.Invalid as e:
        logger.error("YAML configuration is invalid: %s", e)
        raise SystemExit(1)

    gerrit_conn = GerritRestConnection(
        config.gerrit_base_url,
        auth=(config.gerrit_user, config.gerrit_password) if config.gerrit_password else None,
        redis=TorriRedis(config.redis_url),
    )
    source = GerritSource(connection=gerrit_conn, redis=gerrit_conn.redis)

    kafka_bootstrap = config.kafka_bootstrap_servers
    merger_base_url = config.merger_base_url

    scheduler_queue = SchedulerQueue(
        gerrit_conn,
        source,
        yaml_dir=yaml_dir,
        redis_url=config.redis_url,
        kafka_bootstrap=kafka_bootstrap,
        merger_base_url=merger_base_url,
    )

    # gerrit-stream-events: raw Gerrit events → GerritEventProcessor enriches and
    # publishes to trigger-events.
    kafka_conn = KafkaConnection(
        topic=config.kafka_topic_gerrit_stream,
        group_id=config.kafka_group_gerrit_stream,
    )
    kafka_conn.connect()
    event_processor = GerritEventProcessor(kafka_conn, gerrit_conn)
    event_processor.start()

    # trigger-events: enriched events ready for the scheduler.
    trigger_conn = KafkaConnection(
        topic=config.kafka_topic_trigger_events,
        group_id=config.kafka_group_trigger,
    )
    trigger_conn.connect()

    # Bridge: read GerritTriggerEvent dicts from trigger_conn and feed the scheduler.
    def _trigger_bridge():
        from shared.gerritmodel import GerritTriggerEvent
        logger.info("TriggerBridge started")
        while scheduler_queue.is_alive():
            data = trigger_conn.getEvent(timeout=1.0)
            if data is None:
                continue
            logger.debug("TriggerBridge received: type=%s change=%s", data.get("type"), data.get("change_number"))
            try:
                event = GerritTriggerEvent.from_dict(data)
                scheduler_queue.addEvent(event)
                logger.debug("TriggerBridge queued event change=%s to scheduler", event.change_number)
            except Exception:
                logger.exception("Error in trigger bridge processing event: %s", data)
            finally:
                trigger_conn.eventDone()
        logger.warning("TriggerBridge exiting — scheduler_queue is no longer alive")

    scheduler_queue.start()

    bridge_thread = threading.Thread(target=_trigger_bridge, name="TriggerBridge", daemon=True)
    bridge_thread.start()

    # Start the result consumer after the scheduler is running so pipeline_configs are loaded.
    result_consumer = ResultConsumer(
        kafka_bootstrap=kafka_bootstrap,
        redis=TorriRedis(config.redis_url),
        pipeline_names=list(scheduler_queue.pipeline_configs.keys()),
    )
    result_consumer.start()

    logger.info("Scheduler running. Waiting for events...")

    try:
        while scheduler_queue.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    finally:
        event_processor.stop()
        trigger_conn.shutdown(wait=False)
        scheduler_queue.stop()
        logger.info("Scheduler stopped")


def run_server(args):
    pass
