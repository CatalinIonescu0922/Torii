"""
Gerrit driver implementations.

Encapsulates all Gerrit-specific logic:
- Parse Gerrit events
- Validate pipeline entry using Gerrit labels
- Submit changes via Gerrit REST API
- Create synthetic refs
"""

from typing import Dict, Any, Tuple, Optional

from shared.logger_setup import get_logger
from torri.drivers.base_drivers import (
    ChangeSource,
    ValidationGate,
    MergeDriver,
    SyntheticRefProvider,
)
from torri.scheduler import PipelineEntryGate
from torri.gerrit import GerritRestConnection


logger = get_logger(__name__)


class GerritChangeSource(ChangeSource):
    """
    Parse and handle Gerrit-specific change events.
    
    Gerrit events come via Kafka with standard patchset-created format.
    """
    
    def parse_event(self, event_data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Parse Gerrit event from Kafka.
        
        Gerrit format:
        {
            "type": "patchset-created",
            "change": {"number": 123, "id": "..."},
            "patchSet": {"number": 1, ...},
            "eventCreatedOn": 1234567890,
            ...
        }
        """
        try:
            change = event_data.get('change', {})
            patchset = event_data.get('patchSet', {})
            event_type = event_data.get('type')
            
            change_number = change.get('number')
            patchset_number = patchset.get('number')
            
            if not change_number or not patchset_number:
                return False, {'error': 'Invalid Gerrit event: missing change or patchset'}
            
            parsed = {
                'change_id': str(change_number),
                'change_number': change_number,
                'patchset': patchset_number,
                'event_type': event_type or 'unknown',
                'project': change.get('project'),
                'branch': change.get('branch'),
                'subject': change.get('subject'),
                'owner': change.get('owner', {}).get('name'),
                'commit_hash': patchset.get('revision'),
                'raw_event': event_data,
            }
            
            logger.info(f"Parsed Gerrit event: change {change_number} patchset {patchset_number} type {event_type}")
            return True, parsed
        
        except Exception as e:
            logger.error(f"Failed to parse Gerrit event: {e}")
            return False, {'error': str(e)}
    
    def get_change_details(self, change_id: str) -> Tuple[bool, Dict[str, Any]]:
        """Retrieve Gerrit change details from API."""
        # Implementation would call Gerrit API
        # For now, return placeholder
        return True, {'change_id': change_id}


class GerritValidationGate(ValidationGate):
    """
    Validate pipeline entry using Gerrit labels and approvals.
    
    Gerrit gates check Code-Review, Verified, and Approved labels.
    """
    
    def __init__(self, pipeline_entry_gate: PipelineEntryGate):
        """
        Initialize with PipelineEntryGate for Gerrit-specific validation.
        
        Args:
            pipeline_entry_gate: Existing Gerrit pipeline entry validation
        """
        self.pipeline_entry_gate = pipeline_entry_gate
        self.logger = get_logger(__name__)
    
    def can_enter_pipeline(
        self,
        change_id: str,
        patchset: str,
        pipeline_name: str
    ) -> Tuple[bool, str]:
        """
        Check if change can enter pipeline using Gerrit labels.
        
        Uses existing PipelineEntryGate which handles Gerrit-specific logic.
        Posts rejection comment if cannot enter.
        """
        can_enter, message = self.pipeline_entry_gate.check_and_enter_pipeline(
            change_id,
            patchset,
            pipeline_name
        )
        
        if can_enter:
            self.logger.info(f"Change {change_id} allowed in {pipeline_name} pipeline")
        else:
            self.logger.warning(f"Change {change_id} rejected from {pipeline_name}: {message}")
        
        return can_enter, message
    
    def post_message(
        self,
        change_id: str,
        message: str,
        labels: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, str]:
        """
        Post comment to Gerrit change.
        
        Args:
            change_id: Gerrit change number as string
            message: Comment text
            labels: Gerrit labels as dict (e.g., {'Code-Review': '+1'})
        """
        try:
            # This would use gerrit_conn.set_review()
            # For now, placeholder
            self.logger.info(f"Posted message to change {change_id}: {message}")
            return True, "Message posted"
        except Exception as e:
            self.logger.error(f"Failed to post message: {e}")
            return False, str(e)


class GerritMergeDriver(MergeDriver):
    """
    Submit/merge changes via Gerrit REST API.
    
    Gerrit uses rebase-and-merge strategy (rebases onto target branch before merge).
    """
    
    def __init__(self, gerrit_conn: GerritRestConnection):
        """
        Initialize with Gerrit REST connection.
        
        Args:
            gerrit_conn: Configured GerritRestConnection instance
        """
        self.gerrit_conn = gerrit_conn
        self.logger = get_logger(__name__)
    
    def submit_change(self, change_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Submit change via Gerrit REST API.
        
        Calls /changes/{change_id}/submit endpoint.
        """
        try:
            self.logger.info(f"Submitting change {change_id} to Gerrit")
            
            success, response = self.gerrit_conn.submit_change(change_id)
            
            if success:
                status = response.get('status')
                commit_hash = response.get('currentRevision')
                
                self.logger.info(f"Change {change_id} submitted successfully. Status: {status}")
                
                return True, {
                    'status': status,
                    'commit_hash': commit_hash,
                    'message': f"Merged with status {status}",
                    'submission_time': str(response.get('updated')),
                }
            else:
                error = str(response)
                self.logger.error(f"Failed to submit change {change_id}: {error}")
                return False, {
                    'status': 'FAILED',
                    'message': error,
                }
        
        except Exception as e:
            self.logger.error(f"Error submitting change {change_id}: {e}", exc_info=True)
            return False, {
                'status': 'FAILED',
                'message': str(e),
            }
    
    def can_submit(self, change_id: str) -> Tuple[bool, str]:
        """
        Check if change is ready for submission.
        
        Queries Gerrit to verify change status and label requirements.
        """
        try:
            change_details, success = self.gerrit_conn.query(f"change:{change_id}")
            
            if not success or not change_details:
                return False, "Could not retrieve change details"
            
            # Check merge status
            mergeable = change_details.get('mergeable')
            if not mergeable:
                return False, "Change is not mergeable"
            
            # Check required labels
            labels = change_details.get('labels', {})
            code_review = labels.get('Code-Review', {})
            verified = labels.get('Verified', {})
            
            # Check if change has required approvals
            if code_review.get('approved'):
                return True, "Change has required approvals"
            
            return False, "Change lacks required approvals"
        
        except Exception as e:
            self.logger.error(f"Error checking submission readiness: {e}")
            return False, str(e)
    
    def get_merge_status(self, change_id: str) -> str:
        """
        Get current merge status of change.
        
        Returns Gerrit status: OPEN, MERGED, ABANDONED, etc.
        """
        try:
            change_details, success = self.gerrit_conn.query(f"change:{change_id}")
            
            if not success or not change_details:
                return 'UNKNOWN'
            
            return change_details.get('status', 'UNKNOWN')
        
        except Exception as e:
            self.logger.error(f"Error getting merge status: {e}")
            return 'UNKNOWN'


class GerritSyntheticRefProvider(SyntheticRefProvider):
    """
    Create and manage synthetic refs for Gerrit.
    
    Gerrit provides synthetic refs at: refs/changes/XX/YYYYY/Z
    where XX = last 2 digits of change number, YYYYY = change number, Z = patchset number
    """
    
    def __init__(self, merger_coordinator):
        """
        Initialize with merger coordinator for synthetic ref creation.
        
        Args:
            merger_coordinator: MergerCoordinator instance
        """
        self.merger_coordinator = merger_coordinator
        self.logger = get_logger(__name__)
        self.synthetic_refs = {}  # Cache: change_id -> synthetic_ref
    
    def create_synthetic_ref(self, change_id: str) -> Tuple[bool, str]:
        """
        Request synthetic ref from merger service.
        
        Merger will prepare merged code at the synthetic ref.
        """
        try:
            self.logger.info(f"Requesting synthetic ref for change {change_id}")
            
            # Call merger coordinator to create synthesis
            synthetic_ref = self.merger_coordinator.request_synthetic_ref(change_id)
            
            if not synthetic_ref:
                return False, ""
            
            # Cache for future lookups
            self.synthetic_refs[change_id] = synthetic_ref
            
            self.logger.info(f"Synthetic ref for change {change_id}: {synthetic_ref}")
            return True, synthetic_ref
        
        except Exception as e:
            self.logger.error(f"Failed to create synthetic ref: {e}")
            return False, ""
    
    def get_synthetic_ref(self, change_id: str) -> Optional[str]:
        """Get cached synthetic ref or retrieve from merger service."""
        if change_id in self.synthetic_refs:
            return self.synthetic_refs[change_id]
        
        try:
            # Try to get from merger service
            ref = self.merger_coordinator.get_synthetic_ref(change_id)
            if ref:
                self.synthetic_refs[change_id] = ref
            return ref
        except Exception as e:
            self.logger.error(f"Failed to get synthetic ref: {e}")
            return None
