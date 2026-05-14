"""
Pipeline configuration loader and requirement validator.

Responsibilities:
- Load pipeline definitions from YAML
- Validate change meets pipeline requirements
- Check approval labels (required vs rejected)
- Post Gerrit comments when entering pipelines
- Handle failure messages
"""

import yaml
from typing import Dict, List, Optional, Tuple
from shared.logger_setup import get_logger


class PipelineConfig:
    """Single pipeline configuration from YAML."""
    
    def __init__(self, config_dict: dict):
        self.name = config_dict.get('name')
        self.manager = config_dict.get('manager')  # independent or dependent
        self.start_message = config_dict.get('start-message', f'[Torii] Starting {self.name} pipeline')
        self.success_message = config_dict.get('success-message', f'[Torii] {self.name} pipeline succeeded')
        self.failure_message = config_dict.get('failure-message', f'[Torii] {self.name} pipeline failed')
        
        # Requirements
        require_dict = config_dict.get('require', {})
        self.require_open = require_dict.get('open', True)
        self.require_current_patchset = require_dict.get('current-patchset', True)
        self.required_approvals = self._parse_approvals(require_dict.get('approval', []))
        
        # Rejections (if any of these present, change rejected)
        reject_dict = config_dict.get('reject', {})
        self.reject_approvals = self._parse_approvals(reject_dict.get('approval', []))
        
        # Actions on success/failure
        success_gerrit = config_dict.get('success', {}).get('gerrit', [])
        failure_gerrit = config_dict.get('failure', {}).get('gerrit', [])
        
        self.success_labels = self._parse_labels(success_gerrit)
        self.failure_labels = self._parse_labels(failure_gerrit)
        
        # Trigger info (for reference)
        self.trigger = config_dict.get('trigger', {})
    
    @staticmethod
    def _parse_approvals(approval_list: list) -> Dict[str, int]:
        """Convert approval list to dict. Format: [code-review: 2, verified: 1]"""
        result = {}
        for item in approval_list:
            if isinstance(item, dict):
                for label, value in item.items():
                    # Convert label name: code-review → Code-Review
                    normalized_label = PipelineConfig._normalize_label_name(label)
                    result[normalized_label] = value
        return result
    
    @staticmethod
    def _parse_labels(gerrit_list: list) -> Dict[str, int]:
        """Parse Gerrit labels. Format: [Verified: 1]"""
        result = {}
        for item in gerrit_list:
            if isinstance(item, dict):
                for label, value in item.items():
                    normalized_label = PipelineConfig._normalize_label_name(label)
                    result[normalized_label] = value
        return result
    
    @staticmethod
    def _normalize_label_name(label: str) -> str:
        """
        Normalize label name to Gerrit format.
        
        Examples:
        - code-review → Code-Review
        - verified → Verified
        - Code-Review → Code-Review
        - integrated → Integrated
        """
        # Split by hyphens
        parts = label.split('-')
        # Capitalize each part
        normalized = '-'.join(part.capitalize() for part in parts)
        return normalized
    
    def to_dict(self):
        """Serialize to dict."""
        return {
            'name': self.name,
            'manager': self.manager,
            'start_message': self.start_message,
            'failure_message': self.failure_message,
            'require_open': self.require_open,
            'require_current_patchset': self.require_current_patchset,
            'required_approvals': self.required_approvals,
            'reject_approvals': self.reject_approvals,
            'success_labels': self.success_labels,
            'failure_labels': self.failure_labels,
        }


class PipelineConfigLoader:
    """Loads pipeline configurations from YAML file."""
    
    def __init__(self, yaml_file_path: str):
        self.logger = get_logger("torri.scheduler.pipeline_config")
        self.yaml_file = yaml_file_path
        self.pipelines = {}
        self._load()
    
    def _load(self):
        """Load and parse YAML file."""
        try:
            with open(self.yaml_file, 'r') as f:
                data = yaml.safe_load(f)
            
            if not data or 'pipelines' not in data:
                self.logger.warning("No pipelines found in %s", self.yaml_file)
                return
            
            for pipeline_item in data['pipelines']:
                if 'pipeline' in pipeline_item:
                    config = PipelineConfig(pipeline_item['pipeline'])
                    self.pipelines[config.name] = config
                    self.logger.info(
                        "Loaded pipeline: %s (manager=%s)",
                        config.name, config.manager
                    )
            
            self.logger.info("Loaded %d pipelines", len(self.pipelines))
        
        except Exception as e:
            self.logger.error("Failed to load pipelines from %s: %s", self.yaml_file, e)
            raise
    
    def get_pipeline(self, pipeline_name: str) -> Optional[PipelineConfig]:
        """Get pipeline configuration by name."""
        return self.pipelines.get(pipeline_name)
    
    def get_all_pipelines(self) -> Dict[str, PipelineConfig]:
        """Get all loaded pipelines."""
        return self.pipelines


class PipelineRequirementValidator:
    """
    Validates if a change meets pipeline requirements.
    
    Checks:
    - Change is open
    - Change is on current patchset
    - Has all required approvals
    - Doesn't have any rejected approvals
    """
    
    def __init__(self, gerrit_conn):
        self.logger = get_logger("torri.scheduler.pipeline_requirements")
        self.gerrit_conn = gerrit_conn
    
    def can_enter_pipeline(
        self,
        change_number: str,
        patchset: str,
        pipeline_name: str,
        pipeline_config: PipelineConfig
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if change can enter this pipeline.
        
        Returns:
            (can_enter: bool, reason_if_cannot: str or None)
        """
        try:
            # Get change details
            change_data = self.gerrit_conn.query(change_number)[0]
            
            # Check: Change is open
            if pipeline_config.require_open:
                status = change_data.get('status')
                if status != 'NEW':
                    reason = f"Change {change_number} is {status}, not open"
                    self.logger.warning("Rejected from %s: %s", pipeline_name, reason)
                    return False, reason
            
            # Check: Current patchset
            if pipeline_config.require_current_patchset:
                current_revision = change_data.get('current_revision')
                if not current_revision:
                    reason = f"Cannot determine current patchset for change {change_number}"
                    return False, reason
            
            # Check: Required approvals
            labels = change_data.get('labels', {})
            
            # First check: any rejections?
            for reject_label, reject_values in pipeline_config.reject_approvals.items():
                if reject_label in labels:
                    current_value = labels[reject_label].get('value', 0)
                    if isinstance(reject_values, list):
                        if current_value in reject_values:
                            reason = (
                                f"Change cannot enter {pipeline_name}: "
                                f"Label '{reject_label}' has rejected value {current_value}"
                            )
                            self.logger.warning(reason)
                            return False, reason
                    elif current_value == reject_values:
                        reason = (
                            f"Change cannot enter {pipeline_name}: "
                            f"Label '{reject_label}' has rejected value {current_value}"
                        )
                        return False, reason
            
            # Second check: all required approvals present?
            for required_label, required_value in pipeline_config.required_approvals.items():
                if required_label not in labels:
                    reason = (
                        f"Change cannot enter {pipeline_name}: "
                        f"Missing required label '{required_label}'"
                    )
                    self.logger.warning(reason)
                    return False, reason
                
                current_value = labels[required_label].get('value', 0)
                if current_value < required_value:
                    reason = (
                        f"Change cannot enter {pipeline_name}: "
                        f"Label '{required_label}' value is {current_value}, needs {required_value}"
                    )
                    self.logger.warning(reason)
                    return False, reason
            
            # All checks passed
            self.logger.info("Change %s can enter pipeline %s", change_number, pipeline_name)
            return True, None
        
        except Exception as e:
            self.logger.error("Error validating requirements: %s", e)
            return False, f"Validation error: {str(e)}"
    
    def post_start_message(
        self,
        change_number: str,
        patchset: str,
        message: str
    ) -> bool:
        """
        Post start message to change before entering pipeline.
        """
        try:
            self.logger.info(
                "Posting start message to change %s patchset %s",
                change_number, patchset
            )
            
            success = self.gerrit_conn.set_review(
                change_number,
                patchset,
                message
            )
            
            return success
        
        except Exception as e:
            self.logger.error("Error posting start message: %s", e)
            return False
    
    def post_failure_message(
        self,
        change_number: str,
        patchset: str,
        pipeline_name: str,
        reason: str
    ) -> bool:
        """
        Post failure message when change cannot enter pipeline.
        """
        try:
            message = (
                f"Cannot enter {pipeline_name} pipeline: {reason}\n"
                f"Please fix the issues and try again."
            )
            
            self.logger.info(
                "Posting rejection message to change %s patchset %s",
                change_number, patchset
            )
            
            success = self.gerrit_conn.set_review(
                change_number,
                patchset,
                message
            )
            
            return success
        
        except Exception as e:
            self.logger.error("Error posting failure message: %s", e)
            return False


class PipelineEntryGate:
    """
    Main gate for pipeline entry.
    
    Orchestrates:
    1. Load pipeline config
    2. Validate requirements
    3. Post appropriate messages to Gerrit
    4. Allow or reject entry
    """
    
    def __init__(self, gerrit_conn, pipeline_config_loader):
        self.logger = get_logger("torri.scheduler.pipeline_entry_gate")
        self.gerrit_conn = gerrit_conn
        self.config_loader = pipeline_config_loader
        self.validator = PipelineRequirementValidator(gerrit_conn)
    
    def check_and_enter_pipeline(
        self,
        change_number: str,
        patchset: str,
        pipeline_name: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Complete pipeline entry check.
        
        If enters: posts start_message and returns True
        If rejected: posts failure reason and returns False
        
        Returns:
            (can_enter: bool, message: str or error_reason: str)
        """
        try:
            # Get pipeline config
            pipeline_config = self.config_loader.get_pipeline(pipeline_name)
            if not pipeline_config:
                reason = f"Unknown pipeline: {pipeline_name}"
                self.logger.error(reason)
                return False, reason
            
            # Validate requirements
            can_enter, rejection_reason = self.validator.can_enter_pipeline(
                change_number,
                patchset,
                pipeline_name,
                pipeline_config
            )
            
            if can_enter:
                # Post start message
                self.validator.post_start_message(
                    change_number,
                    patchset,
                    pipeline_config.start_message
                )
                
                self.logger.info(
                    "Change %s entered pipeline %s",
                    change_number, pipeline_name
                )
                return True, pipeline_config.start_message
            
            else:
                # Post rejection message
                self.validator.post_failure_message(
                    change_number,
                    patchset,
                    pipeline_name,
                    rejection_reason
                )
                
                return False, rejection_reason
        
        except Exception as e:
            self.logger.error("Error in pipeline entry gate: %s", e)
            return False, f"Gate error: {str(e)}"
