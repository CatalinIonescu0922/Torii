"""
Message template system for preparing Gerrit feedback messages.
Supports variable substitution and dynamic content generation.
"""

import re
from typing import Dict, Any, Optional
from datetime import datetime
from shared.logger_setup import get_logger
from torri.scheduler.config_loader import ConfigurationLoader


class MessageTemplate:
    """
    Handles Gerrit message templating with variable substitution.
    
    Supported variables:
    - {pipeline_name}: Name of the pipeline
    - {position}: Queue position (1-based)
    - {queue_length}: Total queue length
    - {estimated_time}: Estimated wait time in minutes
    - {jobs}: Comma-separated job names
    - {failed_jobs}: Comma-separated failed jobs
    - {job_name}: Name of specific job
    - {build_url}: URL to build logs
    - {vote_label}: Label name that will be voted
    - {vote_value}: Vote value (+1, -1, etc)
    """
    
    def __init__(self, config_loader: ConfigurationLoader):
        self.logger = get_logger("torri.scheduler.messages")
        self.config = config_loader
    
    def get_enqueued_message(self, pipeline_id: str, 
                            position: int = None,
                            queue_length: int = None,
                            estimated_time: str = None) -> str:
        """Generate enqueue status message."""
        try:
            pipeline_config = self.config.get_pipeline_config(pipeline_id)
            if not pipeline_config:
                return f"Enqueued to {pipeline_id}"
            
            # Get template from pipeline config
            template = pipeline_config.gerrit_messages.get(
                'enqueued',
                'Enqueued to {pipeline_name}'
            )
            
            # Prepare substitution variables
            variables = {
                'pipeline_name': pipeline_config.name,
                'position': position or 'N/A',
                'queue_length': queue_length or 'N/A',
                'estimated_time': estimated_time or 'unknown',
            }
            
            return self._substitute(template, variables)
        
        except Exception as e:
            self.logger.error("Error generating enqueued message: %s", e)
            return f"Enqueued to {pipeline_id}"
    
    def get_started_message(self, pipeline_id: str,
                           jobs: Optional[list] = None) -> str:
        """Generate pipeline started message."""
        try:
            pipeline_config = self.config.get_pipeline_config(pipeline_id)
            if not pipeline_config:
                return f"Started {pipeline_id}"
            
            template = pipeline_config.gerrit_messages.get(
                'started',
                'Pipeline {pipeline_name} started, running {jobs}'
            )
            
            jobs_list = ', '.join(jobs) if jobs else ', '.join(pipeline_config.jobs)
            
            variables = {
                'pipeline_name': pipeline_config.name,
                'jobs': jobs_list,
            }
            
            return self._substitute(template, variables)
        
        except Exception as e:
            self.logger.error("Error generating started message: %s", e)
            return f"Started {pipeline_id}"
    
    def get_success_message(self, pipeline_id: str,
                           vote_label: str = 'verified',
                           vote_value: int = 1) -> str:
        """Generate success message."""
        try:
            pipeline_config = self.config.get_pipeline_config(pipeline_id)
            if not pipeline_config:
                return f"{pipeline_id} passed"
            
            template = pipeline_config.gerrit_messages.get(
                'success',
                '{pipeline_name} PASSED'
            )
            
            variables = {
                'pipeline_name': pipeline_config.name,
                'vote_label': vote_label,
                'vote_value': f'{vote_value:+d}',
            }
            
            return self._substitute(template, variables)
        
        except Exception as e:
            self.logger.error("Error generating success message: %s", e)
            return f"{pipeline_id} passed"
    
    def get_failure_message(self, pipeline_id: str,
                           failed_jobs: Optional[list] = None) -> str:
        """Generate failure message."""
        try:
            pipeline_config = self.config.get_pipeline_config(pipeline_id)
            if not pipeline_config:
                return f"{pipeline_id} failed"
            
            template = pipeline_config.gerrit_messages.get(
                'failure',
                '{pipeline_name} FAILED. Failed: {failed_jobs}'
            )
            
            failed_list = ', '.join(failed_jobs) if failed_jobs else 'unknown'
            
            variables = {
                'pipeline_name': pipeline_config.name,
                'failed_jobs': failed_list,
            }
            
            return self._substitute(template, variables)
        
        except Exception as e:
            self.logger.error("Error generating failure message: %s", e)
            return f"{pipeline_id} failed"
    
    def get_rejection_message(self, reason: str) -> str:
        """Generate rejection message for unapproved changes."""
        return (
            f"Cannot enqueue: {reason}\n\n"
            f"Please request necessary approvals before retrying."
        )
    
    def _substitute(self, template: str, variables: Dict[str, Any]) -> str:
        """Replace {var} placeholders with values."""
        try:
            result = template
            for key, value in variables.items():
                placeholder = f"{{{key}}}"
                result = result.replace(placeholder, str(value))
            
            remaining = re.findall(r'\{[^}]+\}', result)
            if remaining:
                self.logger.debug("Unsubstituted placeholders: %s", remaining)
            
            return result
        
        except Exception as e:
            self.logger.error("Error substituting template: %s", e)
            return template
    
    @staticmethod
    def estimate_wait_time(queue_position: int, avg_job_duration: int = 300) -> str:
        """Estimate pipeline completion time."""
        if queue_position <= 0:
            return "now"
        
        total_seconds = queue_position * avg_job_duration
        minutes = total_seconds // 60
        
        if minutes < 1:
            return "< 1 minute"
        elif minutes == 1:
            return "~1 minute"
        else:
            return f"~{minutes} minutes"


class ApprovalRequiredMessage:
    """
    Helper to generate messages for approval requirements.
    """
    
    @staticmethod
    def missing_approval(label_name: str, required_value: int, current_value: int) -> str:
        """Generate message for missing approval."""
        return (
            f"Approval Required\n\n"
            f"Label: {label_name}\n"
            f"Required: {required_value:+d}\n"
            f"Current: {current_value:+d}\n\n"
            f"Please request review."
        )
    
    @staticmethod
    def all_required_approvals(required_list: list) -> str:
        """Generate message listing all required approvals."""
        items = "\n".join([f"• {item}" for item in required_list])
        return (
            f"Waiting for approvals:\n"
            f"{items}\n\n"
            f"Edit Change -> Add reviewers -> Request review"
        )


class PositionInQueueFormatter:
    """
    Formats queue position information for user display.
    """
    
    @staticmethod
    def format_position(position: int, queue_length: int) -> str:
        """Format queue position for display (e.g., 1/5 or Processing)."""
        if position <= 0:
            return "Processing"
        return f"{position}/{queue_length}"
