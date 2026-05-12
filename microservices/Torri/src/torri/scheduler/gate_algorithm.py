"""
Gate pipeline algorithm - orchestrates ordered, dependent execution.

Implements the complete Gate algorithm:
- Speculative execution with merge base calculation
- Failure cascading
- Merge conflict handling
- Pre-merge validation
"""

from typing import List, Optional, Tuple
from datetime import datetime
from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedis
from torri.scheduler.dependency_manager import DependencyManager
from torri.scheduler.merge_coordinator import MergeCoordinator
from torri.scheduler.speculative_merger import SpeculativeMerger
from torri.scheduler.merger_coordinator import MergerCoordinator


class GateAlgorithm:
    """
    Core gate pipeline algorithm for ordered, dependent change processing.
    """
    
    def __init__(self, redis_client: TorriRedis, gerrit_conn, merger_coordinator=None):
        self.logger = get_logger("torri.scheduler.gate_algorithm")
        self.redis = redis_client
        self.gerrit_conn = gerrit_conn
        self.merger_coordinator = merger_coordinator
        
        self.dependencies = DependencyManager(redis_client)
        self.merge_coordinator = MergeCoordinator(redis_client)
        self.speculative_merger = SpeculativeMerger(redis_client, gerrit_conn)
    
    # ========== Phase 1: Queuing ==========
    
    def enqueue_change(self, change_id: str, project_name: str, branch: str) -> int:
        """Enqueue change for gate processing."""
        try:
            # Get current queue
            queue_key = f"torri:pipeline:gate:queue"
            queue = self.redis.queue_list_all(queue_key)
            position = len(queue)
            
            # Register in dependency tracker
            self.dependencies.register_change(change_id, position)
            
            # Calculate initial merge base
            merge_base_hash, applied_changes = self.speculative_merger.calculate_merge_base(
                change_id=change_id,
                queue_position=position,
                earlier_changes=queue,
                current_branch=branch
            )
            
            # Store merge base
            self.speculative_merger.store_merge_base(change_id, merge_base_hash, applied_changes)
            
            # Enqueue
            self.redis.queue_enqueue(queue_key, change_id)
            
            self.logger.info(
                "Enqueued change %s to gate (position %d, base %s)",
                change_id, position, merge_base_hash[:8]
            )
            
            return position
        except Exception as e:
            self.logger.error("Error enqueueing change: %s", e)
            raise
    
    # ========== Phase 2: Speculative Execution ==========
    
    def start_speculative_testing(self, change_id: str) -> Tuple[bool, Optional[str]]:
        """
        Begin speculative test execution with calculated merge base.
        
        Returns:
            (can_test, reason_if_cannot)
        """
        try:
            # Get merge base
            merge_base_info = self.speculative_merger.get_merge_base(change_id)
            if not merge_base_info:
                return False, "Merge base not calculated"
            
            merge_base_hash = merge_base_info.get('hash')
            
            # Check if change can merge on this base
            can_merge, reason = self.speculative_merger.can_merge_speculatively(
                change_id,
                merge_base_hash
            )
            
            if not can_merge:
                self.logger.warning(
                    "Change %s cannot merge on base %s: %s",
                    change_id, merge_base_hash[:8], reason
                )
                return False, reason
            
            # Update state
            state_key = f"torri:change:{change_id}:state"
            self.redis.update_state(state_key, {
                'status': 'TESTING',
                'merge_base': merge_base_hash,
                'applied_changes': merge_base_info.get('applied_changes', []),
            })
            
            self.logger.info(
                "Starting speculative testing for %s on base %s",
                change_id, merge_base_hash[:8]
            )
            
            return True, None
        except Exception as e:
            self.logger.error("Error starting speculative testing: %s", e)
            return False, str(e)
    
    # ========== Phase 3: Test Result Handling ==========
    
    def handle_test_success(self, change_id: str) -> bool:
        """
        Tests passed for this change.
        Mark as MERGE_READY.
        """
        try:
            state_key = f"torri:change:{change_id}:state"
            self.redis.update_state(state_key, {
                'status': 'MERGE_READY',
                'gate_test_status': 'PASSED',
                'test_completion_time': datetime.utcnow().isoformat(),
            })
            
            self.logger.info("Change %s passed gate tests, ready for merge", change_id)
            return True
        except Exception as e:
            self.logger.error("Error handling test success: %s", e)
            return False
    
    def handle_test_failure(self, change_id: str, failure_reason: str) -> List[str]:
        """
        Tests failed for this change.
        Cascade failure to dependents, notify user.
        
        Returns:
            List of affected changes (dependents)
        """
        try:
            # Update state
            state_key = f"torri:change:{change_id}:state"
            self.redis.update_state(state_key, {
                'status': 'FAILED',
                'gate_test_status': 'FAILED',
                'failure_reason': failure_reason,
                'failure_time': datetime.utcnow().isoformat(),
            })
            
            # Cascade to dependents
            affected = self.dependencies.notify_dependents_of_failure(change_id)
            
            self.logger.warning(
                "Change %s failed gate tests (%s), affecting %d dependents",
                change_id, failure_reason, len(affected)
            )
            
            return affected
        except Exception as e:
            self.logger.error("Error handling test failure: %s", e)
            return []
    
    # ========== Phase 4: Merge Handling ==========
    
    def attempt_merge(self, change_id: str, gerrit_change) -> Tuple[bool, Optional[str]]:
        """
        Attempt to merge a change.
        
        Handles:
        1. Pre-merge validation
        2. Merge lock acquisition
        3. Merge execution
        4. Conflict handling with rebase
        
        Returns:
            (merge_successful, failure_reason)
        """
        try:
            # Validate before merge
            valid, reason = self.merge_coordinator.validate_before_merge(change_id, gerrit_change)
            if not valid:
                self.logger.warning("Merge validation failed for %s: %s", change_id, reason)
                return False, reason
            
            # Acquire merge lock
            pipeline_id = "gate"
            if not self.merge_coordinator.acquire_merge_lock(pipeline_id):
                self.logger.debug("Could not acquire merge lock for %s (another scheduler merging)", change_id)
                return False, "Merge lock held by another scheduler"
            
            try:
                # Execute merge
                merge_success = self._execute_merge(change_id, gerrit_change)
                
                if merge_success:
                    # Update state
                    state_key = f"torri:change:{change_id}:state"
                    self.redis.update_state(state_key, {
                        'status': 'MERGED',
                        'merge_time': datetime.utcnow().isoformat(),
                    })
                    
                    # Record attempt
                    self.merge_coordinator.record_merge_attempt(change_id, True)
                    
                    self.logger.info("Successfully merged change %s", change_id)
                    return True, None
                else:
                    # Merge failed - might be conflict
                    self.merge_coordinator.record_merge_attempt(
                        change_id, False,
                        "Merge operation failed"
                    )
                    
                    # Check if should retry with rebase
                    if self.merge_coordinator.should_retry_merge(change_id):
                        self.logger.info(
                            "Merge failed for %s, will retry after rebase",
                            change_id
                        )
                        return False, "Merge failed, will retry"
                    else:
                        return False, "Merge failed, max retries exceeded"
            
            finally:
                self.merge_coordinator.release_merge_lock(pipeline_id)
        
        except Exception as e:
            self.logger.error("Error attempting merge: %s", e)
            self.merge_coordinator.record_merge_attempt(change_id, False, str(e))
            return False, f"Merge error: {str(e)}"
    
    def handle_merge_conflict(
        self,
        change_id: str,
        old_merge_base: str,
        new_merge_base: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Main branch changed, change's merge base is now invalid.
        Need to rebase and restart testing.
        
        Returns:
            (rebase_successful, reason_if_failed)
        """
        try:
            # Attempt rebase
            rebase_success, reason = self.speculative_merger.handle_rebase_needed(
                change_id,
                new_merge_base,
                old_merge_base
            )
            
            if rebase_success:
                # Update merge base
                self.speculative_merger.store_merge_base(
                    change_id,
                    new_merge_base,
                    []  # Will recalculate applied changes
                )
                
                # Mark as needing retest
                state_key = f"torri:change:{change_id}:state"
                self.redis.update_state(state_key, {
                    'status': 'RETEST_NEEDED',
                    'rebase_reason': 'Main branch diverged',
                    'old_base': old_merge_base,
                    'new_base': new_merge_base,
                })
                
                self.logger.info(
                    "Rebased change %s, restarting tests on new base %s",
                    change_id, new_merge_base[:8]
                )
                return True, None
            else:
                self.logger.warning(
                    "Rebase failed for %s: %s",
                    change_id, reason
                )
                return False, reason
        
        except Exception as e:
            self.logger.error("Error handling merge conflict: %s", e)
            return False, str(e)
    
    # ========== Phase 5: Queue Processing ==========
    
    def process_queue(
        self,
        pipeline_id: str,
        window_size: int
    ) -> List[str]:
        """
        Main queue processing loop.
        Dequeues changes when window slots available.
        
        Returns:
            List of changes started in this cycle
        """
        try:
            queue_key = f"torri:pipeline:{pipeline_id}:queue"
            window_key = f"torri:pipeline:{pipeline_id}:window"
            
            # Get current state
            queue = self.redis.queue_list_all(queue_key)
            window_data = self.redis.get_state(window_key) or {'active': 0}
            active_count = window_data.get('active', 0)
            
            available_slots = window_size - active_count
            started = []
            
            # Fill available slots
            for _ in range(available_slots):
                if not queue:
                    break
                
                change_id = self.redis.queue_dequeue(queue_key)
                if change_id:
                    # Start testing
                    can_test, reason = self.start_speculative_testing(change_id)
                    if can_test:
                        started.append(change_id)
                        active_count += 1
                    else:
                        # Cannot test, re-enqueue or fail
                        self.logger.warning(
                            "Cannot test change %s: %s",
                            change_id, reason
                        )
            
            # Update window
            self.redis.set_state(window_key, {
                'size': window_size,
                'active': active_count,
            })
            
            if started:
                self.logger.debug(
                    "Gate processing: started %d changes (active now %d/%d)",
                    len(started), active_count, window_size
                )
            
            return started
        
        except Exception as e:
            self.logger.error("Error processing queue: %s", e)
            return []
    
    # ========== Helper Methods ==========
    
    def _execute_merge(self, change_id: str, gerrit_change) -> bool:
        """
        Submit change to Gerrit via REST API.
        
        Gerrit will use the repo's configured merge strategy.
        No need to check mergeable first - Gerrit will reject if can't merge.
        """
        try:
            change_number = gerrit_change.get('_number') or gerrit_change.get('number') or change_id
            
            self.logger.info("Submitting change %s to Gerrit", change_id)
            
            # Call Gerrit REST API - no strategy specified, uses repo default
            success, response = self.gerrit_conn.submit_change(str(change_number))
            
            if success:
                status = response.get('status')
                self.logger.info(
                    "Successfully submitted change %s, status: %s",
                    change_id, status
                )
                return True
            else:
                error_msg = response
                self.logger.error("Failed to submit change %s: %s", change_id, error_msg)
                return False
                
        except Exception as e:
            self.logger.error("Error executing merge: %s", e, exc_info=True)
            return False
    
    def cleanup_change(self, change_id: str):
        """Clean up all state for a change after completion."""
        try:
            self.dependencies.clean_up_change(change_id)
            self.merge_coordinator.cleanup_merge_state(change_id)
            self.logger.debug("Cleaned up state for change %s", change_id)
        except Exception as e:
            self.logger.error("Error cleaning up change: %s", e)
