"""
Gerrit change implementation.

Extends abstract Change class with Gerrit-specific logic for merge readiness and merging.
"""

from typing import Tuple, Optional, Dict, Any
from shared.logger_setup import get_logger
from torri.change import Change, MergeStatus


class GerritChange(Change):
    """
    Gerrit-specific change implementation.
    
    Handles merge readiness checks and merge operations for Gerrit changes.
    """
    
    def __init__(self, connection_name: str, gerrit_connection):
        """
        Initialize Gerrit change.
        
        Args:
            connection_name: Name of Gerrit connection
            gerrit_connection: GerritRestConnection instance
        """
        super().__init__(source='gerrit', connection_name=connection_name)
        self.gerrit_connection = gerrit_connection
        self.logger = get_logger(__name__)
        
        # Gerrit-specific fields
        self.change_number = None
        self.patchset = None
        self.labels = {}
        self.messages = []
        self.change_details = None
    
    def canMerge(self) -> Tuple[bool, str]:
        """
        Check if Gerrit change is ready for merge.
        
        Gerrit merge criteria:
        1. Change is in OPEN status
        2. Current revision is mergeable (no conflicts)
        3. Has required labels:
           - Code-Review: +2 (approved)
           - Verified: +1 (if configured)
        4. No negative votes (-1 or -2 on blocking labels)
        5. Has merge permission
        
        Returns:
            (can_merge: bool, reason: str)
        """
        try:
            if not self.change_number:
                return False, "Change number not set"
            
            # Query change details if not already loaded
            if not self.change_details:
                self.logger.debug(f"Querying change {self.change_number} for merge check")
                data, related = self.gerrit_connection.query(self.change_number)
                self.change_details = data
                self._update_from_details(data)
            
            # Check status
            if self.status != 'OPEN':
                return False, f"Change is {self.status}, not OPEN"
            
            # Check mergeable field
            if not self.change_details.get('mergeable', False):
                return False, "Change has merge conflicts"
            
            # Check labels
            labels = self.change_details.get('labels', {})
            
            # Check Code-Review
            code_review = labels.get('Code-Review', {})
            code_review_approved = code_review.get('approved', False)
            code_review_votes = code_review.get('all', [])
            
            # Check for negative votes
            for vote in code_review_votes:
                value = vote.get('value', 0)
                if value < 0:
                    reviewer_name = vote.get('name', 'Unknown')
                    return False, f"Code-Review {value} from {reviewer_name}"
            
            if not code_review_approved:
                return False, "Waiting for Code-Review +2"
            
            # Optionally check Verified label
            verified = labels.get('Verified', {})
            verified_approved = verified.get('approved', False)
            verified_votes = verified.get('all', [])
            
            # If Verified label is used, check it
            if 'Verified' in labels and 'values' in labels.get('Verified', {}):
                for vote in verified_votes:
                    value = vote.get('value', 0)
                    if value < 0:
                        return False, "Change has negative Verified vote"
                
                if not verified_approved and len(verified_votes) == 0:
                    # Only check if label exists and is required
                    if labels.get('Verified', {}).get('values'):
                        return False, "Waiting for Verified vote"
            
            self.logger.info(f"Change {self.change_number} is ready to merge")
            return True, "All merge criteria met"
        
        except Exception as e:
            error_msg = f"Error checking merge readiness: {e}"
            self.logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    def merge(self) -> Tuple[bool, Dict[str, Any]]:
        """
        Merge change via Gerrit REST API.
        
        Endpoint: POST /a/changes/{change-id}/submit
        
        Returns:
            (success: bool, response: Dict)
        """
        try:
            if not self.change_number:
                return False, {'message': 'Change number not set'}
            
            self.logger.info(f"Submitting change {self.change_number} to Gerrit")
            
            # Call Gerrit REST API to submit
            success, gerrit_response = self.gerrit_connection.submit_change(
                self.change_number
            )
            
            if success:
                merged_status = gerrit_response.get('status')
                
                response = {
                    'status': 'MERGED' if merged_status == 'MERGED' else 'FAILED',
                    'merged_by': gerrit_response.get('submitted_together', {}).get('owner', {}).get('name'),
                    'merged_at': str(gerrit_response.get('updated')),
                    'commit_sha': gerrit_response.get('current_revision'),
                    'message': f"Change merged with status {merged_status}",
                }
                
                self.logger.info(f"Change {self.change_number} merged successfully")
                return True, response
            else:
                error = gerrit_response if isinstance(gerrit_response, str) else str(gerrit_response)
                
                response = {
                    'status': 'FAILED',
                    'message': error,
                    'errors': error,
                }
                
                self.logger.error(f"Failed to merge change {self.change_number}: {error}")
                return False, response
        
        except Exception as e:
            error_msg = f"Error merging change: {e}"
            self.logger.error(error_msg, exc_info=True)
            return False, {
                'status': 'FAILED',
                'message': error_msg,
                'errors': error_msg,
            }
    
    def getMergeStatus(self) -> MergeStatus:
        """
        Get merge status from Gerrit.
        
        Returns:
            MergeStatus enum value
        """
        try:
            if not self.change_number:
                return MergeStatus.UNKNOWN
            
            # Query current status
            data, _ = self.gerrit_connection.query(self.change_number)
            self._update_from_details(data)
            
            status = data.get('status', 'UNKNOWN')
            
            if status == 'MERGED':
                return MergeStatus.MERGED
            elif status == 'ABANDONED':
                return MergeStatus.ABANDONED
            elif status == 'OPEN':
                return MergeStatus.OPEN
            else:
                return MergeStatus.UNKNOWN
        
        except Exception as e:
            self.logger.warning(f"Error getting merge status: {e}")
            return MergeStatus.UNKNOWN
    
    def postMessage(self, message: str, labels: Optional[Dict] = None) -> bool:
        """
        Post review comment and optional labels to Gerrit change.
        
        Args:
            message: Comment text
            labels: Gerrit labels dict, e.g., {'Code-Review': 1, 'Verified': 1}
        
        Returns:
            bool: Success status
        """
        try:
            if not self.change_number or not self.patchset:
                self.logger.warning("Cannot post message: change_number or patchset not set")
                return False
            
            success = self.gerrit_connection.set_review(
                self.change_number,
                self.patchset,
                message,
                labels or {}
            )
            
            if success:
                self.logger.info(f"Posted message to change {self.change_number}")
            else:
                self.logger.warning(f"Failed to post message to change {self.change_number}")
            
            return success
        
        except Exception as e:
            self.logger.error(f"Error posting message: {e}")
            return False
    
    def _update_from_details(self, change_data: Dict[str, Any]):
        """
        Update change fields from Gerrit API response.
        
        Args:
            change_data: Change details dict from Gerrit REST API
        """
        try:
            self.change_number = str(change_data.get('number', ''))
            self.change_id = change_data.get('id', '')
            self.project = str(change_data.get('project', ''))
            self.branch = str(change_data.get('branch', ''))
            self.status = str(change_data.get('status', ''))
            self.author = change_data.get('owner', {}).get('name', '')
            
            # Get current patchset
            current_revision = change_data.get('current_revision')
            if current_revision:
                revisions = change_data.get('revisions', {})
                current = revisions.get(current_revision, {})
                self.patchset = str(current.get('_number', ''))
            
            self.labels = change_data.get('labels', {})
            self.messages = change_data.get('messages', [])
        
        except Exception as e:
            self.logger.error(f"Error updating from details: {e}")
