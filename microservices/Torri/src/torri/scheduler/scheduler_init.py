"""
Torri Scheduler Initialization System.

Startup sequence:
1. Load configuration from torii.conf
2. Validate configuration file locations
3. Load and parse all YAML files
4. Create configuration objects
5. Inject into scheduler
6. Report status
"""

import os
import sys
from typing import Dict, Optional, Tuple
import yaml

from shared.logger_setup import get_logger, setup_logging
from torri.config.config_manager import initialize_config, get_config
from torri.scheduler import (
    PipelineConfigLoader,
    PipelineConfig,
)


class SchedulerInitializer:
    """
    Initialize Torri scheduler with all required configurations.
    
    Responsibilities:
    1. Load and validate configuration
    2. Load and validate all YAML files
    3. Create pipeline, project, and job objects
    4. Provide initialized components to scheduler
    """
    
    def __init__(self):
        """Initialize the scheduler initializer."""
        self.logger = None
        self.config = None
        self.pipeline_loader = None
        self.projects_config = None
        self.jobs_config = None
        self.errors = []
        self.warnings = []
    
    def initialize(self, config_file: Optional[str] = None) -> Tuple[bool, str]:
        """
        Complete initialization sequence.
        
        Args:
            config_file: Optional path to torii.conf
        
        Returns:
            (success: bool, status_message: str)
        """
        try:
            # Step 1: Setup logging
            print("📋 Initializing Torri Scheduler...")
            print("=" * 60)
            
            # Step 2: Load configuration
            print("\n1️⃣  Loading configuration...")
            self.config = self._load_configuration(config_file)
            if not self.config:
                return False, "Failed to load configuration"
            print("   ✅ Configuration loaded")
            
            # Initialize logger AFTER loading config
            self.logger = get_logger('torri.scheduler.init')
            self.logger.info("Configuration loaded successfully")
            
            # Step 3: Validate file locations
            print("\n2️⃣  Validating configuration files...")
            if not self._validate_files():
                error_msg = f"File validation failed:\n" + "\n".join(self.errors)
                print(f"   ❌ {error_msg}")
                return False, error_msg
            print("   ✅ All required files found")
            
            # Step 4: Load YAML files
            print("\n3️⃣  Loading YAML configuration files...")
            if not self._load_yaml_files():
                error_msg = f"YAML loading failed:\n" + "\n".join(self.errors)
                print(f"   ❌ {error_msg}")
                return False, error_msg
            print("   ✅ All YAML files loaded")
            
            # Step 5: Validate YAML content
            print("\n4️⃣  Validating YAML content...")
            if not self._validate_yaml_content():
                error_msg = f"YAML validation failed:\n" + "\n".join(self.errors)
                print(f"   ❌ {error_msg}")
                return False, error_msg
            print("   ✅ All YAML content valid")
            
            # Step 6: Create configuration objects
            print("\n5️⃣  Creating configuration objects...")
            if not self._create_config_objects():
                error_msg = f"Object creation failed:\n" + "\n".join(self.errors)
                print(f"   ❌ {error_msg}")
                return False, error_msg
            print("   ✅ Configuration objects created")
            
            # Step 7: Report status
            print("\n" + "=" * 60)
            print("✅ SCHEDULER INITIALIZATION SUCCESSFUL")
            print("=" * 60)
            
            status = self._get_status_report()
            print(status)
            
            self.logger.info("Scheduler initialization complete")
            return True, "Scheduler initialized successfully"
        
        except Exception as e:
            error_msg = f"Initialization failed: {str(e)}"
            print(f"   ❌ {error_msg}")
            if self.logger:
                self.logger.exception("Initialization error")
            return False, error_msg
    
    def _load_configuration(self, config_file: Optional[str]) -> Optional[object]:
        """Load configuration from file."""
        try:
            config = initialize_config(config_file)
            return config
        except FileNotFoundError as e:
            self.errors.append(f"Configuration file not found: {str(e)}")
            return None
        except Exception as e:
            self.errors.append(f"Failed to load configuration: {str(e)}")
            return None
    
    def _validate_files(self) -> bool:
        """Validate that all required files exist."""
        try:
            success = self.config.validate_files_exist()
            
            if not success:
                # Log which files are missing
                for name, path in [
                    ('pipelines', self.config.pipelines_yaml_path),
                    ('projects', self.config.projects_yaml_path),
                    ('jobs', self.config.jobs_yaml_path),
                ]:
                    if not os.path.exists(path):
                        self.errors.append(f"   Missing: {name} ({path})")
            
            return success
        
        except Exception as e:
            self.errors.append(f"File validation error: {str(e)}")
            return False
    
    def _load_yaml_files(self) -> bool:
        """Load all YAML configuration files."""
        try:
            # Load pipelines
            print("   • Loading pipelines.yaml...", end=" ")
            self.pipeline_loader = PipelineConfigLoader(
                self.config.pipelines_yaml_path
            )
            pipelines_count = len(self.pipeline_loader.get_all_pipelines())
            print(f"✅ ({pipelines_count} pipelines)")
            
            # Load projects
            print("   • Loading projects.yaml...", end=" ")
            with open(self.config.projects_yaml_path, 'r') as f:
                self.projects_config = yaml.safe_load(f) or {}
            projects_count = len(self.projects_config.get('projects', []))
            print(f"✅ ({projects_count} projects)")
            
            # Load jobs
            print("   • Loading jobs.yaml...", end=" ")
            with open(self.config.jobs_yaml_path, 'r') as f:
                self.jobs_config = yaml.safe_load(f) or {}
            jobs_count = len(self.jobs_config.get('jobs', []))
            print(f"✅ ({jobs_count} jobs)")
            
            return True
        
        except FileNotFoundError as e:
            self.errors.append(f"YAML file not found: {str(e)}")
            return False
        except yaml.YAMLError as e:
            self.errors.append(f"YAML parsing error: {str(e)}")
            return False
        except Exception as e:
            self.errors.append(f"Error loading YAML files: {str(e)}")
            return False
    
    def _validate_yaml_content(self) -> bool:
        """Validate structure and content of YAML files."""
        try:
            # Validate pipelines
            pipelines = self.pipeline_loader.get_all_pipelines()
            if not pipelines:
                self.errors.append("No pipelines defined in pipelines.yaml")
                return False
            
            for name, config in pipelines.items():
                if not name or not config.manager:
                    self.errors.append(f"Invalid pipeline: {name} (missing required fields)")
                    return False
            
            print(f"   ✅ Validated {len(pipelines)} pipelines")
            
            # Validate projects
            projects_list = self.projects_config.get('projects', [])
            if not projects_list:
                self.warnings.append("No projects defined in projects.yaml")
            else:
                for project in projects_list:
                    if not project.get('name'):
                        self.errors.append("Invalid project: missing 'name' field")
                        return False
                
                print(f"   ✅ Validated {len(projects_list)} projects")
            
            # Validate jobs
            jobs_list = self.jobs_config.get('jobs', [])
            if not jobs_list:
                self.warnings.append("No jobs defined in jobs.yaml")
            else:
                for job in jobs_list:
                    if not job.get('name'):
                        self.errors.append("Invalid job: missing 'name' field")
                        return False
                
                print(f"   ✅ Validated {len(jobs_list)} jobs")
            
            return True
        
        except Exception as e:
            self.errors.append(f"Content validation error: {str(e)}")
            return False
    
    def _create_config_objects(self) -> bool:
        """Create configuration objects from YAML data."""
        try:
            # Pipeline objects are already created by PipelineConfigLoader
            pipelines = self.pipeline_loader.get_all_pipelines()
            pipeline_count = len(pipelines)
            print(f"   • Pipeline objects: {pipeline_count} ready")
            
            # Create project objects (placeholder - expand as needed)
            projects_list = self.projects_config.get('projects', [])
            project_count = len(projects_list)
            print(f"   • Project objects: {project_count} ready")
            
            # Create job objects (placeholder - expand as needed)
            jobs_list = self.jobs_config.get('jobs', [])
            job_count = len(jobs_list)
            print(f"   • Job objects: {job_count} ready")
            
            return True
        
        except Exception as e:
            self.errors.append(f"Object creation error: {str(e)}")
            return False
    
    def _get_status_report(self) -> str:
        """Generate status report."""
        report = []
        report.append("\t📊 Startup Report:")
        report.append(f"\t├─ Configuration file: {self.config.config_file}")
        report.append(f"\t├─ Config directory: {self.config.scheduler_config_dir}")
        
        pipelines = self.pipeline_loader.get_all_pipelines()
        report.append(f"\t├─ Pipelines loaded: {len(pipelines)}")
        for name in pipelines:
            report.append(f"\t│  └─ {name}")
        
        projects = self.projects_config.get('projects', [])
        report.append(f"\t├─ Projects loaded: {len(projects)}")
        if len(projects) <= 5:
            for project in projects:
                report.append(f"\t│  └─ {project.get('name', '?')}")
        else:
            for project in projects[:3]:
                report.append(f"\t│  └─ {project.get('name', '?')}")
            report.append(f"\t│  └─ ... and {len(projects) - 3} more")
        
        jobs = self.jobs_config.get('jobs', [])
        report.append(f"\t├─ Jobs loaded: {len(jobs)}")
        
        # Connection info
        report.append(f"\t├─ Gerrit server: {self.config.gerrit_server}:{self.config.gerrit_rest_port}")
        report.append(f"\t├─ Kafka servers: {self.config.kafka_bootstrap_servers}")
        report.append(f"\t├─ Redis server: {self.config.redis_host}:{self.config.redis_port}")
        report.append(f"\t└─ Status: ✅ Ready")
        
        if self.warnings:
            report.append(f"\n\t⚠️  Warnings:")
            for warning in self.warnings:
                report.append(f"\t  • {warning}")
        
        return "\n".join(report)
    
    def get_pipeline_loader(self) -> Optional[object]:
        """Get initialized pipeline loader."""
        return self.pipeline_loader
    
    def get_projects_config(self) -> dict:
        """Get projects configuration."""
        return self.projects_config or {}
    
    def get_jobs_config(self) -> dict:
        """Get jobs configuration."""
        return self.jobs_config or {}
    
    def get_config(self) -> Optional[object]:
        """Get configuration manager."""
        return self.config


def main():
    """
    Main entry point for scheduler initialization.
    
    Call this during scheduler startup to initialize all systems.
    """
    initializer = SchedulerInitializer()
    success, message = initializer.initialize()
    
    if not success:
        print(f"\n❌ Initialization failed: {message}")
        sys.exit(1)
    
    print(f"\n✅ {message}")
    print("\n🚀 Scheduler ready to process changes!\n")
    
    return initializer


if __name__ == '__main__':
    main()
