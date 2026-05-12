"""
Dependency tracking for gate pipeline changes.

Manages:
- Change dependencies (which changes must complete before others)
- Cascade failures (when one change fails, notify dependents)
- Queue reordering (when dependencies change)
"""

from typing import Dict, List, Set, Optional
from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedis, REDIS_KEYS


class DependencyManager:
    """Tracks dependencies between changes in gate pipeline."""
    
    def __init__(self, redis_client: TorriRedis):
        self.logger = get_logger("torri.scheduler.dependencies")
        self.redis = redis_client
    
    def register_change(self, change_id: str, position_in_queue: int):
        """Register change with its queue position."""
        try:
            dep_key = REDIS_KEYS.get('change_dependencies', 'torri:change:{change_id}:dependencies').format(change_id=change_id)
            self.redis.set_state(dep_key, {
                'change_id': change_id,
                'queue_position': position_in_queue,
                'depends_on': [],
                'dependent_of': [],
            })
            self.logger.debug("Registered change %s at position %d", change_id, position_in_queue)
        except Exception as e:
            self.logger.error("Error registering change: %s", e)
    
    def set_dependencies(self, change_id: str, dependent_changes: List[str]):
        """Set which changes depend on this one."""
        try:
            dep_key = f"torri:change:{change_id}:dependencies"
            current = self.redis.get_state(dep_key)
            if current:
                current['dependent_of'] = dependent_changes
                self.redis.set_state(dep_key, current)
            self.logger.debug("Change %s has dependents: %s", change_id, dependent_changes)
        except Exception as e:
            self.logger.error("Error setting dependencies: %s", e)
    
    def get_dependents(self, change_id: str) -> List[str]:
        """Get all changes that depend on this one."""
        try:
            dep_key = f"torri:change:{change_id}:dependencies"
            dep_data = self.redis.get_state(dep_key)
            if dep_data:
                return dep_data.get('dependent_of', [])
            return []
        except Exception as e:
            self.logger.error("Error getting dependents: %s", e)
            return []
    
    def get_dependencies(self, change_id: str) -> List[str]:
        """Get all changes this one depends on."""
        try:
            dep_key = f"torri:change:{change_id}:dependencies"
            dep_data = self.redis.get_state(dep_key)
            if dep_data:
                return dep_data.get('depends_on', [])
            return []
        except Exception as e:
            self.logger.error("Error getting dependencies: %s", e)
            return []
    
    def notify_dependents_of_failure(self, failed_change_id: str) -> List[str]:
        """
        When a change fails, mark all dependents as needing restart.
        Returns list of affected change IDs.
        """
        try:
            dependents = self.get_dependents(failed_change_id)
            affected = []
            
            for dependent_id in dependents:
                # Mark dependent as needing requeue
                state_key = f"torri:change:{dependent_id}:state"
                self.redis.update_state(state_key, {
                    'status': 'requeue_needed',
                    'reason': f'Dependency {failed_change_id} failed',
                })
                affected.append(dependent_id)
            
            self.logger.warning(
                "Change %s failed, affecting dependents: %s",
                failed_change_id, affected
            )
            return affected
        except Exception as e:
            self.logger.error("Error notifying dependents: %s", e)
            return []
    
    def get_queue_order(self, queue: List[str]) -> List[str]:
        """
        Reorder queue respecting dependencies.
        Changes with earlier dependencies come first.
        """
        try:
            ordered = []
            remaining = set(queue)
            
            while remaining:
                # Find change with no dependencies in remaining set
                for change_id in remaining:
                    deps = self.get_dependencies(change_id)
                    deps_in_remaining = [d for d in deps if d in remaining]
                    
                    if not deps_in_remaining:
                        # This change has no unmet dependencies
                        ordered.append(change_id)
                        remaining.remove(change_id)
                        break
                else:
                    # Circular dependency detected
                    self.logger.error("Circular dependency detected in queue: %s", remaining)
                    ordered.extend(remaining)
                    break
            
            return ordered
        except Exception as e:
            self.logger.error("Error getting queue order: %s", e)
            return queue
    
    def calculate_merge_base_position(self, change_id: str, queue: List[str]) -> int:
        """
        Calculate which changes should be included in this change's merge base.
        All changes before this one in queue are included.
        """
        try:
            if change_id not in queue:
                return -1
            
            position = queue.index(change_id)
            # All changes at positions 0 to position-1 are in the merge base
            return position
        except Exception as e:
            self.logger.error("Error calculating merge base position: %s", e)
            return -1
    
    def update_merge_base(self, change_id: str, merge_base_hash: str, base_changes: List[str]):
        """Update the merge base for a change."""
        try:
            state_key = f"torri:change:{change_id}:merge_base"
            self.redis.set_state(state_key, {
                'merge_base_hash': merge_base_hash,
                'base_changes': base_changes,
            })
            self.logger.debug(
                "Updated merge base for %s: %s (from changes: %s)",
                change_id, merge_base_hash[:8], base_changes
            )
        except Exception as e:
            self.logger.error("Error updating merge base: %s", e)
    
    def clean_up_change(self, change_id: str):
        """Remove change and its dependency records."""
        try:
            dep_key = f"torri:change:{change_id}:dependencies"
            base_key = f"torri:change:{change_id}:merge_base"
            self.redis.delete(dep_key)
            self.redis.delete(base_key)
            self.logger.debug("Cleaned up dependencies for change %s", change_id)
        except Exception as e:
            self.logger.error("Error cleaning up change: %s", e)
