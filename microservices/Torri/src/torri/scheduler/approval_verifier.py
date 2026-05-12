"""
Approval label verification for scheduler enqueue decisions.
"""

from typing import Tuple, Optional, Dict, Any
from shared.logger_setup import get_logger
from torri.gerrit.gerritconnection import GerritRestConnection
from torri.scheduler.config_loader import ConfigurationLoader


class ApprovalVerifier:
    """
    Verifies if change meets approval requirements before enqueuing.
    """
    
    def __init__(self, gerrit_conn: GerritRestConnection, config_loader: ConfigurationLoader):
        self.logger = get_logger("torri.scheduler.approval")
        self.gerrit = gerrit_conn
        self.config = config_loader
    
    def verify_project_approval(self, change_id: str, project_name: str) \
            -> Tuple[bool, Optional[str]]:
        """Verify project-level approval requirements."""
        try:
            project_config = self.config.get_project_config(project_name)
            if not project_config:
                self.logger.warning("Project config not found: %s", project_name)
                return False, f"Unknown project: {project_name}"
            
            change = self.gerrit.getChange(change_id)
            if not change:
                return False, f"Change not found: {change_id}"
            
            current_labels = self._extract_labels(change)
            
            for required_label in project_config.approval_labels:
                current_value = current_labels.get(required_label.name, 0)
                
                if current_value < required_label.value:
                    denial_reason = (
                        f"Missing approval: {required_label.name} needs "
                        f"{required_label.value:+d}, currently {current_value:+d}"
                    )
                    self.logger.info(
                        "Change %s approval denied: %s", change_id, denial_reason
                    )
                    return False, denial_reason
            
            self.logger.info("Change %s approved for project %s", change_id, project_name)
            return True, None
        
        except Exception as e:
            self.logger.error(
                "Error verifying project approval for %s: %s", change_id, e, exc_info=True
            )
            return False, f"Error checking approvals: {str(e)}"
    
    def verify_pipeline_approval(self, change_id: str, pipeline_id: str) \
            -> Tuple[bool, Optional[str]]:
        """Verify pipeline-specific approval requirements."""
        try:
            pipeline_config = self.config.get_pipeline_config(pipeline_id)
            if not pipeline_config:
                self.logger.warning("Pipeline config not found: %s", pipeline_id)
                return False, f"Unknown pipeline: {pipeline_id}"
            
            if not pipeline_config.approval_labels:
                return True, None
            
            change = self.gerrit.getChange(change_id)
            if not change:
                return False, f"Change not found: {change_id}"
            
            current_labels = self._extract_labels(change)
            
            for required_label in pipeline_config.approval_labels:
                current_value = current_labels.get(required_label.name, 0)
                
                if current_value < required_label.value:
                    denial_reason = (
                        f"Pipeline '{pipeline_id}' requires {required_label.name} "
                        f"{required_label.value:+d}, currently {current_value:+d}"
                    )
                    self.logger.info(
                        "Change %s approval denied for pipeline %s: %s",
                        change_id, pipeline_id, denial_reason
                    )
                    return False, denial_reason
            
            self.logger.info("Change %s approved for pipeline %s", change_id, pipeline_id)
            return True, None
        
        except Exception as e:
            self.logger.error(
                "Error verifying pipeline approval for %s: %s", change_id, e, exc_info=True
            )
            return False, f"Error checking pipeline approvals: {str(e)}"
    
    def _extract_labels(self, change: Dict[str, Any]) -> Dict[str, int]:
        """Extract approval labels from change object."""
        labels = {}
        if 'labels' in change:
            for label_name, label_info in change['labels'].items():
                if 'value' in label_info:
                    labels[label_name] = label_info['value']
        return labels
