# Torri Scheduler: Configuration, Validation & Gerrit Integration

Complete implementation for YAML-based configuration, custom validation, label verification, and Gerrit messaging.

---

## Part 1: YAML Configuration Schema

### 1.1 Project-Based Configuration

```yaml
# File: microservices/Torri/src/torri/config/layout/projects.yaml
# Define validation rules and merge strategies per project

projects:
  - name: "libraries/common-utils"
    merge_strategy: "rebase"
    
    # Approval labels required to enqueue to gate
    approval_labels:
      - label: "verified"
        required_value: 1
        description: "Code verified by CI"
      
      - label: "code-review"
        required_value: 1
        description: "Reviewed by maintainer"
    
    # Pipelines that apply to this project
    pipelines:
      - pipeline_id: "check"
      - pipeline_id: "gate"
      - pipeline_id: "post"

  - name: "services/api"
    merge_strategy: "squash"
    
    approval_labels:
      - label: "verified"
        required_value: 1
      
      - label: "code-review"
        required_value: 2  # Requires 2 approvals
    
    pipelines:
      - pipeline_id: "check"
      - pipeline_id: "gate"
      - pipeline_id: "post"

  - name: "web/frontend"
    merge_strategy: "merge"
    
    approval_labels:
      - label: "verified"
        required_value: 1
    
    pipelines:
      - pipeline_id: "check"
      - pipeline_id: "gate"
```

### 1.2 Pipeline Configuration with Messages

```yaml
# File: microservices/Torri/src/torri/config/layout/pipelines.yaml
# Define pipelines with job sequences and Gerrit messaging

tenants:
  - name: "default"
    
    pipelines:
      # CHECK PIPELINE: Independent, parallel testing
      - id: "check"
        name: "Check Pipeline"
        type: "check"
        description: "Verify code quality on every patchset"
        
        # Trigger conditions
        trigger_on:
          - event: "patchset-created"
          - event: "change-updated"
        
        # Jobs to run
        jobs:
          - name: "lint"
            timeout: 300
            runs_on: "executor-1"
          
          - name: "unit-tests"
            timeout: 600
            runs_on: "executor-1"
          
          - name: "security-scan"
            timeout: 900
            runs_on: "executor-2"
        
        # Pipeline behavior
        window_size: 5         # Allow 5 parallel changes
        depend_sequential: false
        
        # GERRIT MESSAGING: What to tell users
        gerrit_messages:
          started: |
            🔍 Torri: Starting check pipeline...
            Running jobs: lint, unit-tests, security-scan
            Expected duration: ~10 minutes
          
          success: |
            ✓ Torri: Check pipeline PASSED
            All tests passed successfully!
            
            You can now submit the change for review.
          
          failure: |
            ✗ Torri: Check pipeline FAILED
            Please fix the errors and push a new patchset.
            
            Failed jobs: {failed_jobs}
            See details: {build_url}
          
          error: |
            ⚠ Torri: Check pipeline ERROR
            An infrastructure error occurred.
            Please contact the admins.

      # GATE PIPELINE: Serial, merge validation
      - id: "gate"
        name: "Gate Pipeline"
        type: "gate"
        description: "Pre-merge validation - must pass before merge"
        
        trigger_on:
          - event: "change-ready"
            # Triggered when change ready for merge
          - event: "change-updated"
        
        # Gate jobs (more thorough than check)
        jobs:
          - name: "compile"
            timeout: 600
            runs_on: "executor-1"
          
          - name: "integration-tests"
            timeout: 1800
            runs_on: "executor-2"
          
          - name: "performance-tests"
            timeout: 3600
            runs_on: "executor-3"
        
        # Gate behavior
        window_size: 1         # Serial execution
        depend_sequential: true
        
        # Approval requirements for THIS pipeline
        require_approval:
          labels:
            - label: "verified"
              value: 1
            
            - label: "code-review"
              value: 1
        
        # Gate-specific messages
        gerrit_messages:
          enqueued: |
            ⏳ Torri: Change enqueued in gate pipeline
            Position in queue: {position}
            Estimated wait time: {estimated_time}
            
            The change will be tested for integration once it reaches queue position 1.
          
          started: |
            🚀 Torri: Gate pipeline started
            Running integration tests...
            
            Stage 1/3: compile
            Stage 2/3: integration-tests
            Stage 3/3: performance-tests
          
          success: |
            ✓ Torri: Gate pipeline PASSED
            All integration tests passed!
            
            This change is ready to merge.
            Status will be set to: verified +1
          
          failure: |
            ✗ Torri: Gate pipeline FAILED
            Integration tests failed. Cannot merge.
            
            Failed jobs: {failed_jobs}
            Please rebase and push a new patchset.
          
          # Label voting message
          vote_label: "verified"
          vote_value: 1
          vote_message: "Integration tests passed - verified by CI"

      # POST PIPELINE: After merge
      - id: "post"
        name: "Post Pipeline"
        type: "report"
        description: "Actions after merge (docs, releases)"
        
        trigger_on:
          - event: "change-merged"
        
        jobs:
          - name: "update-docs"
            timeout: 300
            runs_on: "executor-1"
          
          - name: "trigger-release"
            timeout: 600
            runs_on: "executor-1"
        
        window_size: 10
        depend_sequential: false
        
        gerrit_messages:
          started: |
            📦 Torri: Post-merge pipeline started
            Updating documentation and triggering release...
          
          success: |
            ✓ Torri: Post-merge tasks completed
            Documentation updated, release queued.
```

### 1.3 Jobs Configuration

```yaml
# File: microservices/Torri/src/torri/config/layout/jobs.yaml
# Detailed job definitions

jobs:
  - name: "lint"
    description: "Run linter (flake8, black)"
    runs_on: "executor-1"
    timeout: 300
    
    playbooks:
      - "lint.yaml"
    
    vars:
      python_version: "3.10"
      lint_tool: "flake8"
    
    allow_failure: false

  - name: "unit-tests"
    description: "Run unit tests (pytest)"
    runs_on: "executor-1"
    timeout: 600
    
    playbooks:
      - "run-tests.yaml"
    
    vars:
      test_suite: "pytest"
      test_path: "tests/"
      coverage_threshold: 80
    
    allow_failure: false

  - name: "security-scan"
    description: "Security scanning (bandit, safety)"
    runs_on: "executor-2"
    timeout: 900
    
    playbooks:
      - "security-scan.yaml"
    
    vars:
      scan_level: "high"
    
    allow_failure: true  # Warn but don't block

  - name: "compile"
    description: "Build and compile"
    runs_on: "executor-1"
    timeout: 600
    
    playbooks:
      - "build.yaml"
    
    allow_failure: false

  - name: "integration-tests"
    description: "Integration tests"
    runs_on: "executor-2"
    timeout: 1800
    depends_on:
      - "compile"
    
    playbooks:
      - "integration-tests.yaml"
    
    allow_failure: false

  - name: "performance-tests"
    description: "Performance and load tests"
    runs_on: "executor-3"
    timeout: 3600
    depends_on:
      - "compile"
    
    playbooks:
      - "performance-tests.yaml"
    
    allow_failure: true
```

---

## Part 2: Configuration Loader & Validator

### 2.1 Configuration Models (Pydantic)

```python
# File: microservices/Torri/src/torri/config/models.py

from enum import Enum
from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field, validator

class PipelineType(str, Enum):
    CHECK = "check"
    GATE = "gate"
    REPORT = "report"

class JobConfig(BaseModel):
    """Job definition from YAML."""
    name: str
    description: Optional[str] = None
    runs_on: str
    timeout: int = 3600
    
    playbooks: List[str] = Field(default_factory=list)
    vars: Dict[str, Any] = Field(default_factory=dict)
    
    depends_on: List[str] = Field(default_factory=list)
    allow_failure: bool = False
    
    @validator('name')
    def name_valid(cls, v):
        if not v or len(v) < 2:
            raise ValueError("Job name must be at least 2 characters")
        return v

class ApprovalLabel(BaseModel):
    """Approval label requirement."""
    label: str
    required_value: int = 1
    description: Optional[str] = None

class PipelineConfig(BaseModel):
    """Pipeline definition from YAML."""
    id: str
    name: str
    type: PipelineType
    description: Optional[str] = None
    
    trigger_on: List[Dict[str, str]] = Field(default_factory=list)
    jobs: List[Dict[str, Any]] = Field(default_factory=list)
    
    window_size: int = 1
    depend_sequential: bool = False
    
    require_approval: Optional[Dict[str, List[ApprovalLabel]]] = None
    gerrit_messages: Dict[str, str] = Field(default_factory=dict)
    
    @validator('id')
    def id_valid(cls, v):
        if not v or len(v) < 2:
            raise ValueError("Pipeline ID must be at least 2 characters")
        return v

class ProjectConfig(BaseModel):
    """Project configuration."""
    name: str
    merge_strategy: str = "merge"
    
    approval_labels: List[ApprovalLabel] = Field(default_factory=list)
    pipelines: List[Dict[str, str]] = Field(default_factory=list)
    
    @validator('merge_strategy')
    def strategy_valid(cls, v):
        valid_strategies = ["merge", "rebase", "squash", "cherry-pick"]
        if v not in valid_strategies:
            raise ValueError(f"Invalid merge strategy: {v}")
        return v

class TenantConfig(BaseModel):
    """Tenant configuration."""
    name: str
    pipelines: List[PipelineConfig] = Field(default_factory=list)

class ConfigLayout(BaseModel):
    """Complete configuration layout."""
    tenants: List[TenantConfig] = Field(default_factory=list)
    projects: List[ProjectConfig] = Field(default_factory=list)
    jobs_map: Dict[str, JobConfig] = Field(default_factory=dict)
```

### 2.2 Configuration Loader

```python
# File: microservices/Torri/src/torri/config/loader.py

import yaml
import asyncio
from pathlib import Path
from typing import Optional, Dict, List
from shared.logger_setup import get_logger
from torri.config.models import (
    ConfigLayout, TenantConfig, PipelineConfig, ProjectConfig, JobConfig
)

logger = get_logger("torri.config.loader")

class ConfigurationLoader:
    """
    Loads and validates YAML configuration files.
    Custom validation per project and pipeline.
    """
    
    def __init__(self, config_dir: str = "/app/config/layout"):
        self.config_dir = Path(config_dir)
        self.layout: Optional[ConfigLayout] = None
        self.loaded = False

    async def load_all(self) -> ConfigLayout:
        """
        Load and validate all configuration files.
        
        Returns:
            ConfigLayout with validated configuration
        
        Raises:
            ValueError: If validation fails
        """
        logger.info(f"Loading configuration from {self.config_dir}")
        
        try:
            # Load each YAML file
            pipelines_data = await self._load_yaml("pipelines.yaml")
            projects_data = await self._load_yaml("projects.yaml")
            jobs_data = await self._load_yaml("jobs.yaml")
            
            # Build jobs map for reference
            jobs_map = {}
            if jobs_data and "jobs" in jobs_data:
                for job_def in jobs_data["jobs"]:
                    job_config = JobConfig(**job_def)
                    jobs_map[job_config.name] = job_config
            
            # Parse tenants and pipelines
            tenants = []
            if pipelines_data and "tenants" in pipelines_data:
                for tenant_def in pipelines_data["tenants"]:
                    pipeline_configs = []
                    
                    for pipe_def in tenant_def.get("pipelines", []):
                        pipeline_config = PipelineConfig(**pipe_def)
                        pipeline_configs.append(pipeline_config)
                    
                    tenant = TenantConfig(
                        name=tenant_def.get("name", "default"),
                        pipelines=pipeline_configs
                    )
                    tenants.append(tenant)
            
            # Parse projects
            projects = []
            if projects_data and "projects" in projects_data:
                for proj_def in projects_data["projects"]:
                    project_config = ProjectConfig(**proj_def)
                    projects.append(project_config)
            
            # Create layout
            self.layout = ConfigLayout(
                tenants=tenants,
                projects=projects,
                jobs_map=jobs_map
            )
            
            # Validate cross-references
            await self._validate_references()
            
            self.loaded = True
            logger.info(f"✓ Configuration loaded successfully")
            logger.info(f"  - Tenants: {len(tenants)}")
            logger.info(f"  - Projects: {len(projects)}")
            logger.info(f"  - Jobs: {len(jobs_map)}")
            
            return self.layout
            
        except Exception as e:
            logger.error(f"✗ Configuration load failed: {e}", exc_info=True)
            raise

    async def _load_yaml(self, filename: str) -> Dict:
        """Load a single YAML file."""
        filepath = self.config_dir / filename
        
        if not filepath.exists():
            logger.warning(f"Configuration file not found: {filepath}")
            return {}
        
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f)
            logger.debug(f"Loaded {filename}")
            return data or {}
        except yaml.YAMLError as e:
            logger.error(f"YAML syntax error in {filename}: {e}")
            raise ValueError(f"Invalid YAML in {filename}: {e}")

    async def _validate_references(self):
        """
        Cross-validate:
        - All referenced jobs exist
        - All referenced pipelines exist
        - All project pipelines are valid
        """
        logger.info("Validating configuration references...")
        
        # Get all available pipeline IDs
        available_pipelines = set()
        for tenant in self.layout.tenants:
            for pipeline in tenant.pipelines:
                available_pipelines.add(pipeline.id)
        
        # Check projects reference valid pipelines
        for project in self.layout.projects:
            for pipe_ref in project.pipelines:
                if pipe_ref.get("pipeline_id") not in available_pipelines:
                    raise ValueError(
                        f"Project {project.name} references unknown pipeline: "
                        f"{pipe_ref.get('pipeline_id')}"
                    )
        
        # Check pipelines reference valid jobs
        for tenant in self.layout.tenants:
            for pipeline in tenant.pipelines:
                for job_ref in pipeline.jobs:
                    job_name = job_ref.get("name") if isinstance(job_ref, dict) else job_ref
                    if job_name not in self.layout.jobs_map:
                        raise ValueError(
                            f"Pipeline {pipeline.id} references unknown job: {job_name}"
                        )
        
        logger.info("✓ All references valid")

    def get_pipelines_for_project(self, project_name: str) -> List[PipelineConfig]:
        """Get all pipelines that apply to a project."""
        # Find project config
        project = next(
            (p for p in self.layout.projects if p.name == project_name),
            None
        )
        
        if not project:
            logger.warning(f"Project not found: {project_name}")
            return []
        
        # Get referenced pipeline configs
        pipelines = []
        for tenant in self.layout.tenants:
            for pipeline in tenant.pipelines:
                if any(p.get("pipeline_id") == pipeline.id 
                       for p in project.pipelines):
                    pipelines.append(pipeline)
        
        return pipelines

    def get_project_config(self, project_name: str) -> Optional[ProjectConfig]:
        """Get project configuration."""
        return next(
            (p for p in self.layout.projects if p.name == project_name),
            None
        )

    def get_pipeline_config(self, pipeline_id: str) -> Optional[PipelineConfig]:
        """Get pipeline configuration."""
        for tenant in self.layout.tenants:
            for pipeline in tenant.pipelines:
                if pipeline.id == pipeline_id:
                    return pipeline
        return None

    async def reload(self):
        """Hot-reload configuration."""
        logger.info("Reloading configuration...")
        await self.load_all()
        logger.info("✓ Configuration reloaded")
```

---

## Part 3: Label Verification & Change Enqueuing

### 3.1 Approval Verifier

```python
# File: microservices/Torri/src/torri/scheduler/approval_verifier.py

from typing import Dict, List, Optional, Tuple
from shared.logger_setup import get_logger
from torri.config.models import ApprovalLabel

logger = get_logger("torri.scheduler.approval_verifier")

class ApprovalVerifier:
    """
    Verifies that a change has required approvals/labels.
    Prevents enqueueing changes that don't meet gate criteria.
    """
    
    async def verify_pipeline_approval(
        self,
        change_id: str,
        pipeline_config,
        change_labels: Dict[str, int]
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify if change has required approvals for pipeline.
        
        Args:
            change_id: Gerrit change ID
            pipeline_config: PipelineConfig object
            change_labels: Dict of {label_name: current_value}
                          e.g., {"verified": 0, "code-review": 1}
        
        Returns:
            (is_approved, denial_reason)
                is_approved: True if all approvals met
                denial_reason: String explaining why not approved (if False)
        """
        logger.info(f"Verifying approvals for change {change_id}")
        
        # Only gate pipelines have approval requirements
        if not pipeline_config.require_approval:
            logger.debug(f"Pipeline {pipeline_config.id} has no approval requirements")
            return True, None
        
        required_labels = pipeline_config.require_approval.get("labels", [])
        if not required_labels:
            return True, None
        
        missing_approvals = []
        
        for required_label in required_labels:
            label_name = required_label.label
            required_value = required_label.required_value
            current_value = change_labels.get(label_name, 0)
            
            logger.debug(
                f"  Label {label_name}: current={current_value}, "
                f"required={required_value}"
            )
            
            if current_value < required_value:
                missing_approvals.append(
                    f"{label_name}={current_value}/{required_value}"
                )
        
        if missing_approvals:
            reason = f"Missing approvals: {', '.join(missing_approvals)}"
            logger.warning(f"Change {change_id} not approved: {reason}")
            return False, reason
        
        logger.info(f"✓ Change {change_id} has all required approvals")
        return True, None

    async def verify_project_approval(
        self,
        project_name: str,
        change_labels: Dict[str, int],
        project_config
    ) -> Tuple[bool, Optional[str]]:
        """
        Verify if change has required approvals for project.
        (These are checked before ANY pipeline enqueuing)
        
        Returns:
            (is_approved, denial_reason)
        """
        logger.info(f"Verifying project approvals for {project_name}")
        
        if not project_config.approval_labels:
            return True, None
        
        missing_approvals = []
        
        for approval_label in project_config.approval_labels:
            label_name = approval_label.label
            required_value = approval_label.required_value
            current_value = change_labels.get(label_name, 0)
            
            logger.debug(
                f"  Project label {label_name}: current={current_value}, "
                f"required={required_value}"
            )
            
            if current_value < required_value:
                missing_approvals.append(
                    f"{label_name}={current_value}/{required_value}"
                )
        
        if missing_approvals:
            reason = f"Project needs: {', '.join(missing_approvals)}"
            logger.warning(f"Project {project_name} not approved: {reason}")
            return False, reason
        
        logger.info(f"✓ Project {project_name} has all required approvals")
        return True, None
```

---

## Part 4: Gerrit Integration & Messaging

### 4.1 Gerrit Client

```python
# File: microservices/Torri/src/torri/gerrit/gerrit_client.py

import aiohttp
import json
import base64
from typing import Optional, Dict, Any
from urllib.parse import urljoin
from shared.logger_setup import get_logger

logger = get_logger("torri.gerrit.client")

class GerritClient:
    """
    Client for interacting with Gerrit API.
    Posts comments, votes labels, etc.
    """
    
    def __init__(self, gerrit_url: str, username: str, password: str):
        """
        Args:
            gerrit_url: Base Gerrit URL (e.g., "https://gerrit.example.com")
            username: Gerrit username
            password: HTTP password (not account password)
        """
        self.gerrit_url = gerrit_url.rstrip("/")
        self.username = username
        self.password = password
        self.session: Optional[aiohttp.ClientSession] = None

    async def connect(self):
        """Initialize HTTP session with Basic Auth."""
        auth_string = f"{self.username}:{self.password}"
        auth_b64 = base64.b64encode(auth_string.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/json"
        }
        
        self.session = aiohttp.ClientSession(headers=headers)
        logger.info(f"Connected to Gerrit: {self.gerrit_url}")

    async def disconnect(self):
        """Close HTTP session."""
        if self.session:
            await self.session.close()
            logger.info("Disconnected from Gerrit")

    async def post_comment(
        self,
        change_id: str,
        message: str,
        as_draft: bool = False
    ) -> bool:
        """
        Post a comment on a change.
        
        Args:
            change_id: Gerrit change ID (number or hash)
            message: Comment text
            as_draft: If True, post as draft (not visible until published)
        
        Returns:
            True if successful
        """
        try:
            # Gerrit API: /changes/{change_id}/revisions/current/review
            endpoint = f"/a/changes/{change_id}/revisions/current/review"
            url = urljoin(self.gerrit_url, endpoint)
            
            payload = {
                "message": message,
            }
            
            if as_draft:
                payload["drafts"] = "PUBLISH_ALL_REVISIONS"
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"Failed to post comment on {change_id}: "
                        f"{resp.status} - {error_text}"
                    )
                    return False
                
                logger.info(f"✓ Posted comment on change {change_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error posting comment: {e}", exc_info=True)
            return False

    async def set_label(
        self,
        change_id: str,
        label: str,
        value: int,
        message: str = ""
    ) -> bool:
        """
        Vote on a change (set label).
        
        Args:
            change_id: Gerrit change ID
            label: Label name (e.g., "verified", "code-review")
            value: Label value (e.g., -1, 0, 1, 2)
            message: Optional message to post with vote
        
        Returns:
            True if successful
        """
        try:
            endpoint = f"/a/changes/{change_id}/revisions/current/review"
            url = urljoin(self.gerrit_url, endpoint)
            
            payload = {
                "labels": {
                    label: value
                }
            }
            
            if message:
                payload["message"] = message
            
            async with self.session.post(url, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"Failed to set label {label}={value} on {change_id}: "
                        f"{resp.status} - {error_text}"
                    )
                    return False
                
                logger.info(
                    f"✓ Set label {label}={value} on change {change_id}"
                )
                return True
                
        except Exception as e:
            logger.error(f"Error setting label: {e}", exc_info=True)
            return False

    async def get_change(self, change_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch change details from Gerrit.
        
        Returns:
            Change object or None if error
        """
        try:
            endpoint = f"/a/changes/{change_id}/detail"
            url = urljoin(self.gerrit_url, endpoint)
            
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    logger.error(f"Failed to fetch change {change_id}: {resp.status}")
                    return None
                
                # Gerrit API returns ')]}' prefix, need to strip it
                text = await resp.text()
                if text.startswith(")]}"):
                    text = text[4:]
                
                change = json.loads(text)
                logger.debug(f"Fetched change {change_id}")
                return change
                
        except Exception as e:
            logger.error(f"Error fetching change: {e}", exc_info=True)
            return None

    async def get_labels(self, change_id: str) -> Dict[str, int]:
        """
        Get current labels/votes on a change.
        
        Returns:
            Dict of {label_name: current_value}
        """
        try:
            change = await self.get_change(change_id)
            if not change:
                return {}
            
            labels = {}
            for label_name, label_info in change.get("labels", {}).items():
                # Get current value from all votes
                current_value = label_info.get("value", 0)
                labels[label_name] = current_value
            
            logger.debug(f"Labels on change {change_id}: {labels}")
            return labels
            
        except Exception as e:
            logger.error(f"Error getting labels: {e}", exc_info=True)
            return {}
```

### 4.2 Message Template System

```python
# File: microservices/Torri/src/torri/scheduler/message_template.py

from typing import Dict, Any, Optional
from string import Template
from shared.logger_setup import get_logger

logger = get_logger("torri.scheduler.message_template")

class MessageTemplate:
    """
    Handles Gerrit message templating from YAML definitions.
    Substitutes variables like {position}, {estimated_time}, etc.
    """
    
    # Template variables that can be substituted
    AVAILABLE_VARS = {
        "position": "Queue position",
        "estimated_time": "Estimated wait time",
        "failed_jobs": "Comma-separated list of failed jobs",
        "build_url": "URL to build details",
        "pipeline_name": "Name of pipeline",
        "change_id": "Change ID",
    }
    
    def __init__(self, pipeline_config):
        self.pipeline_config = pipeline_config
        self.messages = pipeline_config.gerrit_messages or {}

    def get_message(
        self,
        message_type: str,
        **variables
    ) -> Optional[str]:
        """
        Get a message template for the given type.
        
        Args:
            message_type: Type of message (e.g., "started", "success", "enqueued")
            **variables: Variables to substitute in template
        
        Returns:
            Formatted message or None if not defined
        """
        template_text = self.messages.get(message_type)
        
        if not template_text:
            logger.debug(f"Message type '{message_type}' not defined")
            return None
        
        try:
            # Use Python string.Template for substitution
            template = Template(template_text)
            message = template.safe_substitute(variables)
            
            logger.debug(f"Generated message for {message_type}")
            return message
            
        except Exception as e:
            logger.error(f"Error formatting message: {e}")
            return template_text  # Return original if substitution fails

    def get_enqueued_message(
        self,
        queue_position: int,
        queue_length: int,
        estimated_time_minutes: int = 0
    ) -> Optional[str]:
        """Get formatted 'enqueued' message."""
        estimated_time = f"~{estimated_time_minutes} minutes"
        
        return self.get_message(
            "enqueued",
            position=queue_position,
            estimated_time=estimated_time,
            pipeline_name=self.pipeline_config.name
        )

    def get_started_message(self) -> Optional[str]:
        """Get formatted 'started' message."""
        job_names = ", ".join(job.get("name", "?") for job in self.pipeline_config.jobs)
        
        return self.get_message(
            "started",
            pipeline_name=self.pipeline_config.name,
            jobs=job_names
        )

    def get_success_message(self) -> Optional[str]:
        """Get formatted 'success' message."""
        return self.get_message(
            "success",
            pipeline_name=self.pipeline_config.name
        )

    def get_failure_message(self, failed_jobs: list) -> Optional[str]:
        """Get formatted 'failure' message."""
        failed_jobs_str = ", ".join(failed_jobs)
        
        return self.get_message(
            "failure",
            failed_jobs=failed_jobs_str,
            pipeline_name=self.pipeline_config.name,
            build_url="https://torri.example.com/builds"
        )

    def get_vote_label(self) -> Optional[str]:
        """Get the label to vote on after success."""
        return self.messages.get("vote_label")

    def get_vote_value(self) -> int:
        """Get the vote value (usually 1 for +1)."""
        # Try to parse from messages, default to 1
        return 1

    def get_vote_message(self) -> Optional[str]:
        """Get message to post with vote."""
        return self.messages.get("vote_message")
```

### 4.3 Enqueue Handler with Label Verification

```python
# File: microservices/Torri/src/torri/scheduler/enqueue_handler.py

from typing import Optional
from datetime import datetime
from shared.logger_setup import get_logger
from torri.gerrit.gerrit_client import GerritClient
from torri.scheduler.approval_verifier import ApprovalVerifier
from torri.scheduler.message_template import MessageTemplate

logger = get_logger("torri.scheduler.enqueue_handler")

class EnqueueHandler:
    """
    Handles enqueueing changes to pipelines.
    - Verifies approvals/labels
    - Posts messages to Gerrit
    - Prevents incorrect enqueues
    """
    
    def __init__(
        self,
        redis_client,
        gerrit_client: GerritClient,
        config_loader,
        approval_verifier: ApprovalVerifier
    ):
        self.redis = redis_client
        self.gerrit = gerrit_client
        self.config_loader = config_loader
        self.verifier = approval_verifier

    async def try_enqueue_change(
        self,
        change_id: str,
        project_name: str,
        pipeline_id: str,
        change_data: dict
    ) -> bool:
        """
        Attempt to enqueue a change to a pipeline.
        
        Returns:
            True if successfully enqueued
            False if approval requirements not met (message posted to Gerrit)
        """
        logger.info(
            f"Attempting to enqueue change {change_id} to "
            f"{project_name}:{pipeline_id}"
        )
        
        # Get configurations
        pipeline_config = self.config_loader.get_pipeline_config(pipeline_id)
        project_config = self.config_loader.get_project_config(project_name)
        
        if not pipeline_config or not project_config:
            logger.error(f"Configuration not found for {project_name}:{pipeline_id}")
            return False
        
        # Fetch current labels from Gerrit
        gerrit_labels = await self.gerrit.get_labels(change_id)
        logger.info(f"Current labels on change {change_id}: {gerrit_labels}")
        
        # Check pipeline-specific approvals
        is_approved, denial_reason = await self.verifier.verify_pipeline_approval(
            change_id,
            pipeline_config,
            gerrit_labels
        )
        
        if not is_approved:
            # Post rejection message to Gerrit
            rejection_msg = (
                f"⚠️ Torri: Cannot enqueue to {pipeline_config.name}\n\n"
                f"Reason: {denial_reason}\n\n"
                f"Please request approval from reviewers."
            )
            
            await self.gerrit.post_comment(change_id, rejection_msg)
            logger.warning(f"Change {change_id} not approved for {pipeline_id}")
            return False
        
        # Enqueue change to Redis
        await self.redis.pipeline_enqueue_change(pipeline_id, change_id)
        
        # Get queue position
        queue = await self.redis.pipeline_get_queue(pipeline_id)
        position = queue.index(change_id) + 1 if change_id in queue else -1
        
        # Post enqueued message to Gerrit
        message_template = MessageTemplate(pipeline_config)
        enqueued_msg = message_template.get_enqueued_message(
            queue_position=position,
            queue_length=len(queue),
            estimated_time_minutes=position * 5  # Rough estimate
        )
        
        if enqueued_msg:
            await self.gerrit.post_comment(change_id, enqueued_msg)
        
        logger.info(f"✓ Change {change_id} enqueued to {pipeline_id} at position {position}")
        return True

    async def post_pipeline_started(
        self,
        change_id: str,
        pipeline_id: str
    ):
        """Post 'pipeline started' message to Gerrit."""
        pipeline_config = self.config_loader.get_pipeline_config(pipeline_id)
        if not pipeline_config:
            return
        
        message_template = MessageTemplate(pipeline_config)
        started_msg = message_template.get_started_message()
        
        if started_msg:
            await self.gerrit.post_comment(change_id, started_msg)

    async def post_pipeline_success(
        self,
        change_id: str,
        pipeline_id: str
    ):
        """
        Post 'pipeline success' message and vote label (if configured).
        """
        pipeline_config = self.config_loader.get_pipeline_config(pipeline_id)
        if not pipeline_config:
            return
        
        message_template = MessageTemplate(pipeline_config)
        success_msg = message_template.get_success_message()
        
        # Get label to vote on
        vote_label = message_template.get_vote_label()
        vote_value = message_template.get_vote_value()
        vote_message = message_template.get_vote_message()
        
        # Post message
        if success_msg:
            await self.gerrit.post_comment(change_id, success_msg)
        
        # Vote label (e.g., verified +1)
        if vote_label:
            await self.gerrit.set_label(
                change_id,
                vote_label,
                vote_value,
                message=vote_message or ""
            )

    async def post_pipeline_failure(
        self,
        change_id: str,
        pipeline_id: str,
        failed_jobs: list
    ):
        """Post 'pipeline failure' message to Gerrit."""
        pipeline_config = self.config_loader.get_pipeline_config(pipeline_id)
        if not pipeline_config:
            return
        
        message_template = MessageTemplate(pipeline_config)
        failure_msg = message_template.get_failure_message(failed_jobs)
        
        if failure_msg:
            await self.gerrit.post_comment(change_id, failure_msg)
```

---

## Part 5: Integration into Scheduler

### 5.1 Updated FastAPI Scheduler with All Features

```python
# File: microservices/Torri/src/torri/scheduler/server.py (additions)

# At startup:
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Torri Scheduler initializing...")
    
    # Load configuration
    config_loader = ConfigurationLoader(
        config_dir="/app/config/layout"
    )
    await config_loader.load_all()
    scheduler_state.config_loader = config_loader
    
    # Initialize Gerrit client
    gerrit_client = GerritClient(
        gerrit_url=os.getenv("GERRIT_URL", "http://gerrit:8080"),
        username=os.getenv("GERRIT_USER", "torri"),
        password=os.getenv("GERRIT_PASSWORD", "secret")
    )
    await gerrit_client.connect()
    scheduler_state.gerrit_client = gerrit_client
    
    # Initialize verifier
    approval_verifier = ApprovalVerifier()
    scheduler_state.approval_verifier = approval_verifier
    
    # Initialize enqueue handler
    enqueue_handler = EnqueueHandler(
        redis_client=scheduler_state.redis_client,
        gerrit_client=gerrit_client,
        config_loader=config_loader,
        approval_verifier=approval_verifier
    )
    scheduler_state.enqueue_handler = enqueue_handler
    
    # Rest of initialization...
    yield
    
    # Cleanup
    await gerrit_client.disconnect()

# Event handler for patchset-created:
@app.post("/api/v1/gerrit-event")
async def gerrit_webhook(payload: Dict[str, Any]):
    """Handle Gerrit webhooks with approval verification."""
    
    event_type = payload.get("type")
    if event_type not in ["patchset-created", "change-updated"]:
        return JSONResponse({"status": "ignored"}, status_code=200)
    
    change_data = payload.get("change", {})
    patchset_data = payload.get("patchSet", {})
    
    change_id = change_data.get("number")
    project_name = change_data.get("project")
    
    logger.info(f"📨 Gerrit event: {event_type} for {project_name}#{change_id}")
    
    # Get applicable pipelines for this project
    applicable_pipelines = scheduler_state.config_loader.get_pipelines_for_project(
        project_name
    )
    
    logger.info(
        f"Applicable pipelines for {project_name}: "
        f"{[p.id for p in applicable_pipelines]}"
    )
    
    # Try to enqueue to each pipeline
    for pipeline_config in applicable_pipelines:
        # Check if event triggers this pipeline
        triggered = any(
            trigger.get("event") in event_type
            for trigger in pipeline_config.trigger_on
        )
        
        if not triggered:
            logger.debug(f"Pipeline {pipeline_config.id} not triggered by {event_type}")
            continue
        
        # Attempt enqueue (with approval verification)
        success = await scheduler_state.enqueue_handler.try_enqueue_change(
            change_id=str(change_id),
            project_name=project_name,
            pipeline_id=pipeline_config.id,
            change_data=change_data
        )
        
        if success:
            logger.info(f"✓ Enqueued to {pipeline_config.id}")
        else:
            logger.warning(f"✗ Could not enqueue to {pipeline_config.id}")
    
    return JSONResponse({"status": "processed"}, status_code=202)

# Job completion handler:
@app.post("/api/v1/job-result")
async def job_result_webhook(payload: Dict[str, Any]):
    """Handle job completion with Gerrit feedback."""
    
    job_id = payload.get("job_id")
    build_set_id = payload.get("build_set_id")
    status = payload.get("status")
    
    logger.info(f"Job {job_id} completed with status: {status}")
    
    # Update job state
    await scheduler_state.redis_client.job_set_state(job_id, status, payload)
    
    # Mark pipeline dirty
    build_set = await scheduler_state.redis_client.get_json(
        f"torri:build-set:{build_set_id}"
    )
    if build_set and build_set.get("status") != "COMPLETE":
        pipeline_id = build_set.get("pipeline_id")
        await scheduler_state.redis_client.pipeline_mark_dirty(pipeline_id)
    
    return JSONResponse({"status": "received"}, status_code=202)
```

---

## Part 6: Configuration Examples

### 6.1 Complete pipelines.yaml Example

See section 1.2 above for full example with all message types.

### 6.2 Environment Variables

```bash
# .env for scheduler

GERRIT_URL=http://gerrit:8080
GERRIT_USER=torri
GERRIT_PASSWORD=<http-password>

REDIS_URL=redis://redis:6379/0
KAFKA_SERVER=kafka:9092

CONFIG_DIR=/app/config/layout

LOG_LEVEL=INFO
SCHEDULER_ID=scheduler-1
```

---

## Summary: Complete Flow

```
1. STARTUP
   └─ Load YAML configs (pipelines.yaml, projects.yaml, jobs.yaml)
   └─ Validate configurations and cross-references
   └─ Connect to Gerrit, Redis, Kafka

2. PATCHSET CREATED in Gerrit
   └─ Webhook received at /api/v1/gerrit-event
   └─ Find applicable pipelines for project
   └─ For each pipeline:
      ├─ Check approval requirements
      ├─ If missing: Post rejection message to Gerrit
      ├─ If approved: Enqueue to pipeline
      └─ Post "enqueued" message to Gerrit

3. CHANGE ENTERS QUEUE
   └─ Wait for pipeline to process
   └─ When reached position 1:
      ├─ Post "started" message to Gerrit
      └─ Launch jobs

4. JOBS RUNNING
   └─ Executor runs jobs
   └─ Post logs to Gerrit periodically (optional)

5. JOBS COMPLETE
   └─ If all passed:
      ├─ Post "success" message to Gerrit
      ├─ Vote on label (e.g., verified +1)
      └─ Mark ready for merge
   
   └─ If any failed:
      ├─ Post "failure" message to Gerrit
      ├─ List failed jobs
      └─ Wait for new patchset

6. CHANGE MERGED
   └─ Post "merged" message to Gerrit
   └─ Enqueue to post pipeline
   └─ Run post-merge jobs (docs, releases, etc.)
```
