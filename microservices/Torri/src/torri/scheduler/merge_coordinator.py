"""
Merge coordination for gate pipeline.

Handles:
- Distributed merge locks (prevent concurrent merges)
- Pre-merge validation (conflicts, permissions, etc.)
- Merge state tracking
- Merge retries on conflict
"""

from typing import Tuple, Optional
from datetime import datetime, timedelta
from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedis, REDIS_KEYS


class MergeCoordinator:
    """Coordinates merge operations across multiple scheduler instances."""
    
    MERGE_LOCK_TIMEOUT = 30  # seconds
    MERGE_VALIDATION_TIMEOUT = 60  # seconds
    
    def __init__(self, redis_client: TorriRedis):
        self.logger = get_logger("torri.scheduler.merge_coordinator")
        self.redis = redis_client
    
    def acquire_merge_lock(self, pipeline_id: str) -> bool:
        """
        Attempt to acquire global merge lock for a pipeline.
        Only one scheduler can merge changes at a time per pipeline.
        """
        try:
            lock_key = f"torri:lock:merge:{pipeline_id}"
            acquired = self.redis.acquire_lock(lock_key, timeout=self.MERGE_LOCK_TIMEOUT)
            
            if acquired:
                self.logger.info("Acquired merge lock for pipeline %s", pipeline_id)
            else:
                self.logger.debug("Failed to acquire merge lock for pipeline %s (held by another scheduler)", pipeline_id)
            
            return acquired
        except Exception as e:
            self.logger.error("Error acquiring merge lock: %s", e)
            return False
    
    def release_merge_lock(self, pipeline_id: str):
        """Release merge lock."""
        try:
            lock_key = f"torri:lock:merge:{pipeline_id}"
            self.redis.release_lock(lock_key)
            self.logger.info("Released merge lock for pipeline %s", pipeline_id)
        except Exception as e:
            self.logger.error("Error releasing merge lock: %s", e)
    
    def store_merge_state(self, change_id: str, state: str, details: dict = None):
        """Store merge attempt state."""
        try:
            merge_key = f"torri:change:{change_id}:merge_state"
            state_data = {
                'change_id': change_id,
                'state': state,  # pending, validating, merging, success, failed, conflict
                'details': details or {},
                'timestamp': datetime.utcnow().isoformat(),
            }
            self.redis.set_state(merge_key, state_data)
            self.logger.debug("Stored merge state for %s: %s", change_id, state)
        except Exception as e:
            self.logger.error("Error storing merge state: %s", e)
    
    def get_merge_state(self, change_id: str) -> Optional[dict]:
        """Get current merge state."""
        try:
            merge_key = f"torri:change:{change_id}:merge_state"
            return self.redis.get_state(merge_key)
        except Exception as e:
            self.logger.error("Error getting merge state: %s", e)
            return None
    
    def validate_before_merge(self, change_id: str, gerrit_change) -> Tuple[bool, Optional[str]]:
        """
        Pre-merge validation checklist.
        Returns: (is_valid, reason_if_invalid)
        """
        try:
            # Check 1: Test status
            test_status = self._check_test_status(change_id)
            if not test_status[0]:
                return False, f"Test validation failed: {test_status[1]}"
            
            # Check 2: Merge permissions
            permission_status = self._check_merge_permissions(change_id, gerrit_change)
            if not permission_status[0]:
                return False, f"Permission check failed: {permission_status[1]}"
            
            # Check 3: Still mergeable
            mergeable_status = self._check_mergeable(change_id, gerrit_change)
            if not mergeable_status[0]:
                return False, f"Not mergeable: {mergeable_status[1]}"
            
            # Check 4: Dependencies merges
            dependencies_status = self._check_dependencies_merged(change_id)
            if not dependencies_status[0]:
                return False, f"Dependency not merged: {dependencies_status[1]}"
            
            # Check 5: Branch protection
            protection_status = self._check_branch_protection(change_id, gerrit_change)
            if not protection_status[0]:
                return False, f"Branch protection: {protection_status[1]}"
            
            self.logger.info("Merge validation passed for change %s", change_id)
            return True, None
        
        except Exception as e:
            self.logger.error("Error validating merge: %s", e)
            return False, f"Validation error: {str(e)}"
    
    def _check_test_status(self, change_id: str) -> Tuple[bool, Optional[str]]:
        """Check if all gate tests passed."""
        try:
            state_key = f"torri:change:{change_id}:state"
            state = self.redis.get_state(state_key)
            
            if not state:
                return False, "Change state not found"
            
            if state.get('gate_test_status') != 'PASSED':
                return False, f"Tests not passed: {state.get('gate_test_status', 'unknown')}"
            
            return True, None
        except Exception as e:
            self.logger.error("Error checking test status: %s", e)
            return False, str(e)
    
    def _check_merge_permissions(self, change_id: str, gerrit_change) -> Tuple[bool, Optional[str]]:
        """Check if change has required approvals."""
        try:
            # Check Code-Review approval
            code_review = gerrit_change.get('labels', {}).get('Code-Review', {})
            if isinstance(code_review, dict):
                code_review_value = code_review.get('value', 0)
            else:
                code_review_value = code_review
            
            if code_review_value < 1:
                return False, "Code-Review < +1"
            
            return True, None
        except Exception as e:
            self.logger.error("Error checking merge permissions: %s", e)
            return False, str(e)
    
    def _check_mergeable(self, change_id: str, gerrit_change) -> Tuple[bool, Optional[str]]:
        """Check current mergeable status in Gerrit."""
        try:
            # This would call Gerrit API to check if change can be merged
            # For now, assume mergeable if change status is not declined
            mergeable = gerrit_change.get('mergeable', True)
            
            if not mergeable:
                return False, "Change has merge conflicts"
            
            return True, None
        except Exception as e:
            self.logger.error("Error checking mergeable: %s", e)
            return False, str(e)
    
    def _check_dependencies_merged(self, change_id: str) -> Tuple[bool, Optional[str]]:
        """Check if all dependent changes are already merged."""
        try:
            # Get this change's dependencies
            dep_key = f"torri:change:{change_id}:dependencies"
            dep_data = self.redis.get_state(dep_key)
            
            if not dep_data:
                return True, None
            
            depends_on = dep_data.get('depends_on', [])
            
            for dependency_id in depends_on:
                # Check if dependency is merged
                dep_state_key = f"torri:change:{dependency_id}:state"
                dep_state = self.redis.get_state(dep_state_key)
                
                if not dep_state or dep_state.get('status') != 'merged':
                    return False, f"Dependency {dependency_id} not merged"
            
            return True, None
        except Exception as e:
            self.logger.error("Error checking dependencies: %s", e)
            return False, str(e)
    
    def _check_branch_protection(self, change_id: str, gerrit_change) -> Tuple[bool, Optional[str]]:
        """Check branch protection rules."""
        try:
            # This would check if branch has protection rules
            # For MVP, assume no special protection
            return True, None
        except Exception as e:
            self.logger.error("Error checking branch protection: %s", e)
            return False, str(e)
    
    def record_merge_attempt(self, change_id: str, success: bool, error_message: str = None):
        """Record merge attempt result."""
        try:
            attempt_key = f"torri:change:{change_id}:merge_attempts"
            attempt_data = self.redis.get_state(attempt_key) or {'attempts': []}
            
            attempt_record = {
                'timestamp': datetime.utcnow().isoformat(),
                'success': success,
                'error': error_message,
            }
            
            attempt_data['attempts'].append(attempt_record)
            self.redis.set_state(attempt_key, attempt_data)
            
            self.logger.debug(
                "Recorded merge attempt for %s: success=%s",
                change_id, success
            )
        except Exception as e:
            self.logger.error("Error recording merge attempt: %s", e)
    
    def should_retry_merge(self, change_id: str, max_retries: int = 3) -> bool:
        """Check if merge should be retried."""
        try:
            attempt_key = f"torri:change:{change_id}:merge_attempts"
            attempt_data = self.redis.get_state(attempt_key) or {'attempts': []}
            
            failed_count = sum(
                1 for a in attempt_data['attempts']
                if not a.get('success', False)
            )
            
            should_retry = failed_count < max_retries
            
            if should_retry:
                self.logger.info(
                    "Will retry merge for %s (attempt %d/%d)",
                    change_id, failed_count + 1, max_retries
                )
            else:
                self.logger.warning(
                    "Max merge retries exceeded for %s",
                    change_id
                )
            
            return should_retry
        except Exception as e:
            self.logger.error("Error checking should retry: %s", e)
            return False
    
    def cleanup_merge_state(self, change_id: str):
        """Clean up merge-related state after completion."""
        try:
            merge_key = f"torri:change:{change_id}:merge_state"
            attempt_key = f"torri:change:{change_id}:merge_attempts"
            self.redis.delete(merge_key)
            self.redis.delete(attempt_key)
            self.logger.debug("Cleaned up merge state for %s", change_id)
        except Exception as e:
            self.logger.error("Error cleaning up merge state: %s", e)
