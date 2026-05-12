"""
Speculative merger for gate pipeline.

Handles:
- Calculating merge bases (previous changes + main branch)
- Creating virtual/speculative merge workspaces
- Detecting conflicts
- Rebasing changes on new base
"""

from typing import Tuple, Optional, List
from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedis


class SpeculativeMerger:
    """
    Manages speculative merge bases for gate pipeline testing.
    
    Enables testing changes as if earlier changes are already merged,
    without actually merging them yet.
    """
    
    def __init__(self, redis_client: TorriRedis, gerrit_conn):
        self.logger = get_logger("torri.scheduler.speculative_merger")
        self.redis = redis_client
        self.gerrit_conn = gerrit_conn
    
    def calculate_merge_base(
        self,
        change_id: str,
        queue_position: int,
        earlier_changes: List[str],
        current_branch: str = "main"
    ) -> Tuple[str, List[str]]:
        """
        Calculate the speculative merge base for a change.
        
        Returns:
            (merge_base_commit_hash, applied_changes)
        
        Logic:
        - If position 0: use current branch head
        - If position > 0: calculate virtual merge of all earlier + branch
        """
        try:
            if queue_position == 0:
                # First in queue: use current branch head
                base_hash = self._get_branch_head(current_branch)
                self.logger.info(
                    "Merge base for change %s (pos 0): %s (branch head)",
                    change_id, base_hash[:8]
                )
                return base_hash, []
            else:
                # Calculate virtual merge base
                base_hash = self._get_branch_head(current_branch)
                applied_changes = []
                
                for earlier_change_id in earlier_changes:
                    # Get earlier change that's already tested/merged speculatively
                    change_status = self._get_change_status(earlier_change_id)
                    
                    if change_status == 'MERGED':
                        # Already actually merged to main
                        base_hash = self._virtual_merge(base_hash, earlier_change_id)
                        applied_changes.append(earlier_change_id)
                    elif change_status == 'TESTING':
                        # Speculatively assume it will merge
                        base_hash = self._virtual_merge(base_hash, earlier_change_id)
                        applied_changes.append(earlier_change_id)
                    elif change_status == 'FAILED':
                        # Skip failed changes
                        self.logger.debug(
                            "Skipping failed change %s in merge base",
                            earlier_change_id
                        )
                        pass
                
                self.logger.info(
                    "Merge base for change %s (pos %d): %s (includes %d changes)",
                    change_id, queue_position, base_hash[:8], len(applied_changes)
                )
                return base_hash, applied_changes
        
        except Exception as e:
            self.logger.error("Error calculating merge base: %s", e)
            raise
    
    def can_merge_speculatively(
        self,
        change_id: str,
        merge_base_hash: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if change can merge cleanly on given base without conflicts.
        
        Returns:
            (can_merge, conflict_reason)
        """
        try:
            # Check for merge conflicts
            conflict_detected = self._check_conflict(change_id, merge_base_hash)
            
            if conflict_detected:
                return False, f"Merge conflict with base {merge_base_hash[:8]}"
            
            return True, None
        except Exception as e:
            self.logger.error("Error checking speculative merge: %s", e)
            return False, str(e)
    
    def handle_rebase_needed(
        self,
        change_id: str,
        new_base_hash: str,
        old_base_hash: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Main branch changed, need to rebase change on new base.
        
        This is called when:
        - Someone else merged to main
        - Current base is no longer valid
        
        Returns:
            (rebase_successful, reason_if_failed)
        """
        try:
            # Check if rebase is needed
            if old_base_hash == new_base_hash:
                self.logger.debug(
                    "No rebase needed for %s (base unchanged)",
                    change_id
                )
                return True, None
            
            # Attempt rebase
            rebased = self._attempt_rebase(change_id, old_base_hash, new_base_hash)
            
            if rebased:
                self.logger.info(
                    "Successfully rebased change %s (was on %s, now on %s)",
                    change_id, old_base_hash[:8], new_base_hash[:8]
                )
                return True, None
            else:
                self.logger.warning(
                    "Rebase failed for change %s on %s",
                    change_id, new_base_hash[:8]
                )
                return False, "Rebase conflicts detected"
        
        except Exception as e:
            self.logger.error("Error handling rebase: %s", e)
            return False, str(e)
    
    def store_merge_base(self, change_id: str, merge_base_hash: str, applied_changes: List[str]):
        """Store merge base info for later reference."""
        try:
            base_key = f"torri:change:{change_id}:merge_base"
            base_data = {
                'hash': merge_base_hash,
                'applied_changes': applied_changes,
            }
            self.redis.set_state(base_key, base_data)
            self.logger.debug(
                "Stored merge base for %s: %s",
                change_id, merge_base_hash[:8]
            )
        except Exception as e:
            self.logger.error("Error storing merge base: %s", e)
    
    def get_merge_base(self, change_id: str) -> Optional[dict]:
        """Retrieve stored merge base."""
        try:
            base_key = f"torri:change:{change_id}:merge_base"
            return self.redis.get_state(base_key)
        except Exception as e:
            self.logger.error("Error getting merge base: %s", e)
            return None
    
    # Helper methods (would integrate with actual Git/Gerrit API)
    
    def _get_branch_head(self, branch: str) -> str:
        """Get current HEAD commit of branch."""
        try:
            # This would call git API or Gerrit API
            # For now, return placeholder
            return self.gerrit_conn.getRefHeadCommit(f"refs/heads/{branch}")
        except Exception as e:
            self.logger.error("Error getting branch head: %s", e)
            raise
    
    def _virtual_merge(self, base_hash: str, change_id: str) -> str:
        """
        Calculate what merge base would be if this change merges.
        
        In reality, this would:
        1. Get change's commit
        2. Attempt merge-base calculation
        3. Return new hash (or error if conflict)
        """
        try:
            # This would call git merge-base --octopus or similar
            # For MVP: return placeholder
            merged_hash = f"{base_hash[:7]}_{change_id}"
            return merged_hash
        except Exception as e:
            self.logger.error("Error in virtual merge: %s", e)
            raise
    
    def _check_conflict(self, change_id: str, base_hash: str) -> bool:
        """Check if change would conflict with base."""
        try:
            # This would attempt a test merge
            # For MVP: return False (no conflict)
            return False
        except Exception as e:
            self.logger.error("Error checking conflict: %s", e)
            return True
    
    def _attempt_rebase(
        self,
        change_id: str,
        old_base: str,
        new_base: str
    ) -> bool:
        """Attempt to rebase change from old_base to new_base."""
        try:
            # This would call git rebase API
            # For MVP: return True (success)
            self.logger.debug(
                "Rebasing change %s: %s -> %s",
                change_id, old_base[:8], new_base[:8]
            )
            return True
        except Exception as e:
            self.logger.error("Error rebasing: %s", e)
            return False
    
    def _get_change_status(self, change_id: str) -> str:
        """Get current status of a change."""
        try:
            state_key = f"torri:change:{change_id}:state"
            state = self.redis.get_state(state_key)
            
            if not state:
                return 'UNKNOWN'
            
            status = state.get('status', 'unknown').upper()
            return status
        except Exception as e:
            self.logger.error("Error getting change status: %s", e)
            return 'UNKNOWN'
