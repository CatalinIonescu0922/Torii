"""
Configuration models and loader for Torri scheduler.
Handles YAML-based declarative configuration.
"""

import os
import yaml
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from shared.logger_setup import get_logger


class ApprovalLabel(BaseModel):
    """Represents an approval requirement label."""
    name: str
    value: int
    blocking: bool = False


class JobConfig(BaseModel):
    """Job specification."""
    name: str
    description: Optional[str] = None
    timeout: int = 600
    playbook: Optional[str] = None
    dependencies: List[str] = Field(default_factory=list)
    allow_failure: bool = False


class PipelineConfig(BaseModel):
    """Pipeline configuration."""
    id: str
    name: str
    type: str
    trigger_events: List[str] = Field(default_factory=list)
    jobs: List[str] = Field(default_factory=list)
    window_size: int = 1
    approval_labels: List[ApprovalLabel] = Field(default_factory=list)
    gerrit_messages: Dict[str, str] = Field(
        default_factory=lambda: {
            'enqueued': '',
            'started': '',
            'success': '',
            'failure': ''
        }
    )


class ProjectConfig(BaseModel):
    """Per-project configuration."""
    name: str
    merge_strategy: str = "merge"
    approval_labels: List[ApprovalLabel] = Field(default_factory=list)
    pipelines: List[str] = Field(default_factory=list)


class ConfigLayout(BaseModel):
    """Complete configuration layout."""
    projects: Dict[str, ProjectConfig]
    pipelines: Dict[str, PipelineConfig]
    jobs: Dict[str, JobConfig]


class ConfigurationLoader:
    """Loads and validates YAML-based Torri configuration."""
    
    def __init__(self, config_dir: Optional[str] = None):
        self.logger = get_logger("torri.scheduler.config")
        self.config_dir = config_dir or os.getenv(
            "TORRI_CONFIG_DIR",
            "/app/config/layout"
        )
        self._config: Optional[ConfigLayout] = None
    
    def load_all(self) -> Dict[str, Any]:
        """Load and validate all configuration files."""
        try:
            self.logger.info("Loading configuration from %s", self.config_dir)
            
            projects_yaml = self._load_yaml("projects.yaml")
            pipelines_yaml = self._load_yaml("pipelines.yaml")
            jobs_yaml = self._load_yaml("jobs.yaml")
            
            projects = self._parse_projects(projects_yaml)
            jobs = self._parse_jobs(jobs_yaml)
            pipelines = self._parse_pipelines(pipelines_yaml)
            
            self._validate_references(projects, pipelines, jobs)
            
            self.logger.info(
                "Configuration loaded: %d projects, %d pipelines, %d jobs",
                len(projects), len(pipelines), len(jobs)
            )
            
            return {
                'projects': projects,
                'pipelines': pipelines,
                'jobs': jobs
            }
        
        except Exception as e:
            self.logger.error("Failed to load configuration: %s", e, exc_info=True)
            raise
    
    def _load_yaml(self, filename: str) -> Dict[str, Any]:
        """Load a YAML file."""
        filepath = os.path.join(self.config_dir, filename)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Configuration not found: {filepath}")
        
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f) or {}
            self.logger.debug("Loaded: %s", filename)
            return data
        except yaml.YAMLError as e:
            self.logger.error("YAML parse error in %s: %s", filename, e)
            raise ValueError(f"Invalid YAML in {filename}: {e}")
    
    def _parse_projects(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse projects from YAML."""
        projects = {}
        for project_name, project_data in (data or {}).items():
            try:
                approval_labels = [
                    ApprovalLabel(**label)
                    for label in project_data.get('approval_labels', [])
                ]
                
                projects[project_name] = {
                    'name': project_name,
                    'merge_strategy': project_data.get('merge_strategy', 'merge'),
                    'approval_labels': approval_labels,
                    'pipelines': project_data.get('pipelines', [])
                }
            except Exception as e:
                self.logger.error("Error parsing project %s: %s", project_name, e)
                raise
        
        return projects
    
    def _parse_pipelines(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse pipelines from YAML."""
        pipelines = {}
        for pipeline_id, pipeline_data in (data or {}).items():
            try:
                approval_labels = [
                    ApprovalLabel(**label)
                    for label in pipeline_data.get('approval_labels', [])
                ]
                
                pipelines[pipeline_id] = {
                    'id': pipeline_id,
                    'name': pipeline_data.get('name', pipeline_id),
                    'type': pipeline_data.get('type', 'check'),
                    'trigger_events': pipeline_data.get('trigger_events', []),
                    'jobs': pipeline_data.get('jobs', []),
                    'window_size': pipeline_data.get('window_size', 1),
                    'approval_labels': approval_labels,
                    'gerrit_messages': pipeline_data.get('gerrit_messages', {})
                }
            except Exception as e:
                self.logger.error("Error parsing pipeline %s: %s", pipeline_id, e)
                raise
        
        return pipelines
    
    def _parse_jobs(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse jobs from YAML."""
        jobs = {}
        for job_id, job_data in (data or {}).items():
            try:
                jobs[job_id] = {
                    'name': job_data.get('name', job_id),
                    'description': job_data.get('description'),
                    'timeout': job_data.get('timeout', 600),
                    'playbook': job_data.get('playbook'),
                    'dependencies': job_data.get('dependencies', []),
                    'allow_failure': job_data.get('allow_failure', False)
                }
            except Exception as e:
                self.logger.error("Error parsing job %s: %s", job_id, e)
                raise
        
        return jobs
    
    def _validate_references(self, projects: Dict, pipelines: Dict, jobs: Dict):
        """Validate cross-references between configs."""
        for project_name, project_config in projects.items():
            for pipeline_id in project_config.get('pipelines', []):
                if pipeline_id not in pipelines:
                    raise ValueError(
                        f"Project '{project_name}' references unknown pipeline '{pipeline_id}'"
                    )
        
        for pipeline_id, pipeline_config in pipelines.items():
            for job_id in pipeline_config.get('jobs', []):
                if job_id not in jobs:
                    raise ValueError(
                        f"Pipeline '{pipeline_id}' references unknown job '{job_id}'"
                    )
    
    def get_project_config(self, project_name: str) -> Optional[Any]:
        """Get configuration for a specific project."""
        try:
            config = self.load_all()
            return config.get('projects', {}).get(project_name)
        except Exception as e:
            self.logger.error("Error getting project config for %s: %s", project_name, e)
            return None
    
    def get_pipeline_config(self, pipeline_id: str) -> Optional[Any]:
        """Get configuration for a specific pipeline."""
        try:
            config = self.load_all()
            return config.get('pipelines', {}).get(pipeline_id)
        except Exception as e:
            self.logger.error("Error getting pipeline config for %s: %s", pipeline_id, e)
            return None
