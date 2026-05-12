"""
Unit tests for Gate pipeline algorithm and supporting modules.

Tests cover:
- DependencyManager: Tracking and cascading
- MergeCoordinator: Validation and locking
- SpeculativeMerger: Merge bases and conflicts
- GateAlgorithm: Complete orchestration
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
import sys
import os

# Add src to path for imports
project_root = os.path.dirname(os.path.abspath(__file__))
while not os.path.exists(os.path.join(project_root, 'src')):
    project_root = os.path.dirname(project_root)
    if project_root == '/':
        break

sys.path.insert(0, os.path.join(project_root, 'src'))

from torri.scheduler.dependency_manager import DependencyManager
from torri.scheduler.merge_coordinator import MergeCoordinator
from torri.scheduler.speculative_merger import SpeculativeMerger
from torri.scheduler.gate_algorithm import GateAlgorithm


class MockRedis:
    """Mock Redis client for testing."""
    
    def __init__(self):
        self.data = {}
        self.locks = {}
    
    def get_state(self, key):
        return self.data.get(key)
    
    def set_state(self, key, value):
        self.data[key] = value
    
    def update_state(self, key, updates):
        if key in self.data:
            self.data[key].update(updates)
        else:
            self.data[key] = updates
    
    def delete(self, key):
        if key in self.data:
            del self.data[key]
    
    def queue_enqueue(self, key, value):
        if key not in self.data:
            self.data[key] = []
        self.data[key].append(value)
        return len(self.data[key])
    
    def queue_dequeue(self, key):
        if key in self.data and self.data[key]:
            return self.data[key].pop(0)
        return None
    
    def queue_list_all(self, key):
        return self.data.get(key, [])
    
    def acquire_lock(self, key, timeout=None):
        if key not in self.locks:
            self.locks[key] = True
            return True
        return False
    
    def release_lock(self, key):
        if key in self.locks:
            del self.locks[key]


class TestDependencyManager(unittest.TestCase):
    """Test DependencyManager for tracking change dependencies."""
    
    def setUp(self):
        self.redis = MockRedis()
        self.manager = DependencyManager(self.redis)
    
    def test_register_change(self):
        """Test registering a change with position."""
        self.manager.register_change("100", position_in_queue=0)
        
        dep_data = self.redis.get_state("torri:change:100:dependencies")
        self.assertIsNotNone(dep_data)
        self.assertEqual(dep_data['change_id'], "100")
        self.assertEqual(dep_data['queue_position'], 0)
    
    def test_set_dependencies(self):
        """Test setting which changes depend on this one."""
        self.manager.register_change("100", 0)
        self.manager.set_dependencies("100", ["101", "102"])
        
        dependents = self.manager.get_dependents("100")
        self.assertEqual(dependents, ["101", "102"])
    
    def test_get_dependents(self):
        """Test retrieving dependent changes."""
        self.manager.register_change("100", 0)
        self.manager.set_dependencies("100", ["101"])
        
        dependents = self.manager.get_dependents("100")
        self.assertEqual(dependents, ["101"])
    
    def test_notify_dependents_of_failure(self):
        """Test cascading failure to dependent changes."""
        # Setup: Change 100 has dependents 101 and 102
        self.manager.register_change("100", 0)
        self.manager.set_dependencies("100", ["101", "102"])
        
        # Mark 101 and 102 as testing
        self.redis.set_state("torri:change:101:state", {"status": "TESTING"})
        self.redis.set_state("torri:change:102:state", {"status": "TESTING"})
        
        # Notify about failure
        affected = self.manager.notify_dependents_of_failure("100")
        
        self.assertEqual(len(affected), 2)
        self.assertIn("101", affected)
        self.assertIn("102", affected)
    
    def test_calculate_merge_base_position(self):
        """Test calculating merge base position in queue."""
        queue = ["100", "101", "102", "103"]
        
        # Change at position 0
        pos = self.manager.calculate_merge_base_position("100", queue)
        self.assertEqual(pos, 0)
        
        # Change at position 2 (includes 100, 101 in merge base)
        pos = self.manager.calculate_merge_base_position("102", queue)
        self.assertEqual(pos, 2)
    
    def test_clean_up_change(self):
        """Test cleaning up change state after completion."""
        self.manager.register_change("100", 0)
        self.manager.update_merge_base("100", "abc123", ["99"])
        
        # Verify stored
        self.assertIsNotNone(self.redis.get_state("torri:change:100:dependencies"))
        self.assertIsNotNone(self.redis.get_state("torri:change:100:merge_base"))
        
        # Clean up
        self.manager.clean_up_change("100")
        
        # Verify removed
        self.assertIsNone(self.redis.get_state("torri:change:100:dependencies"))
        self.assertIsNone(self.redis.get_state("torri:change:100:merge_base"))


class TestMergeCoordinator(unittest.TestCase):
    """Test MergeCoordinator for merge validation and locking."""
    
    def setUp(self):
        self.redis = MockRedis()
        self.coordinator = MergeCoordinator(self.redis)
    
    def test_acquire_merge_lock(self):
        """Test acquiring merge lock."""
        acquired = self.coordinator.acquire_merge_lock("gate")
        self.assertTrue(acquired)
        
        # Second attempt should fail
        acquired2 = self.coordinator.acquire_merge_lock("gate")
        self.assertFalse(acquired2)
    
    def test_release_merge_lock(self):
        """Test releasing merge lock."""
        self.coordinator.acquire_merge_lock("gate")
        self.coordinator.release_merge_lock("gate")
        
        # Should be able to acquire again
        acquired = self.coordinator.acquire_merge_lock("gate")
        self.assertTrue(acquired)
    
    def test_store_and_get_merge_state(self):
        """Test storing and retrieving merge state."""
        self.coordinator.store_merge_state("100", "merging", {"attempt": 1})
        
        state = self.coordinator.get_merge_state("100")
        self.assertIsNotNone(state)
        self.assertEqual(state['state'], "merging")
        self.assertEqual(state['details']['attempt'], 1)
    
    def test_validate_before_merge_success(self):
        """Test successful merge validation."""
        # Setup state
        self.redis.set_state("torri:change:100:state", {
            'gate_test_status': 'PASSED'
        })
        
        gerrit_change = {
            'labels': {
                'Code-Review': {'value': 1}
            },
            'mergeable': True,
            'status': 'NEW'
        }
        
        # Validate
        valid, reason = self.coordinator.validate_before_merge("100", gerrit_change)
        
        self.assertTrue(valid)
        self.assertIsNone(reason)
    
    def test_validate_before_merge_test_not_passed(self):
        """Test validation fails when tests not passed."""
        self.redis.set_state("torri:change:100:state", {
            'gate_test_status': 'FAILED'
        })
        
        gerrit_change = {
            'labels': {},
            'mergeable': True,
            'status': 'NEW'
        }
        
        valid, reason = self.coordinator.validate_before_merge("100", gerrit_change)
        
        self.assertFalse(valid)
        self.assertIn("Test", reason)
    
    def test_validate_before_merge_no_approval(self):
        """Test validation fails without Code-Review approval."""
        self.redis.set_state("torri:change:100:state", {
            'gate_test_status': 'PASSED'
        })
        
        gerrit_change = {
            'labels': {'Code-Review': {'value': 0}},
            'mergeable': True,
            'status': 'NEW'
        }
        
        valid, reason = self.coordinator.validate_before_merge("100", gerrit_change)
        
        self.assertFalse(valid)
        self.assertIn("Code-Review", reason)
    
    def test_record_and_check_merge_attempts(self):
        """Test recording merge attempts and retry logic."""
        # Record first failure
        self.coordinator.record_merge_attempt("100", False, "conflict")
        
        # Should allow retry
        should_retry = self.coordinator.should_retry_merge("100", max_retries=3)
        self.assertTrue(should_retry)
        
        # Record two more failures
        self.coordinator.record_merge_attempt("100", False, "conflict")
        self.coordinator.record_merge_attempt("100", False, "conflict")
        
        # Should NOT allow retry (3 failures = max)
        should_retry = self.coordinator.should_retry_merge("100", max_retries=3)
        self.assertFalse(should_retry)


class TestSpeculativeMerger(unittest.TestCase):
    """Test SpeculativeMerger for merge base calculation."""
    
    def setUp(self):
        self.redis = MockRedis()
        self.gerrit_conn = Mock()
        self.merger = SpeculativeMerger(self.redis, self.gerrit_conn)
        
        # Mock git operations
        self.gerrit_conn.getRefHeadCommit = Mock(return_value="main_abc123")
    
    def test_calculate_merge_base_position_zero(self):
        """Test merge base for first change in queue (position 0)."""
        merge_base, applied = self.merger.calculate_merge_base(
            change_id="100",
            queue_position=0,
            earlier_changes=[],
            current_branch="main"
        )
        
        # Should be main branch head
        self.assertEqual(merge_base, "main_abc123")
        self.assertEqual(applied, [])
    
    def test_calculate_merge_base_position_nonzero(self):
        """Test merge base for later changes (position > 0)."""
        # Mock change status for earlier change
        self.redis.set_state("torri:change:99:state", {"status": "MERGED"})
        
        merge_base, applied = self.merger.calculate_merge_base(
            change_id="100",
            queue_position=1,
            earlier_changes=["99"],
            current_branch="main"
        )
        
        # Should include earlier change in base
        self.assertIsNotNone(merge_base)
        self.assertGreater(len(applied), 0)
    
    def test_can_merge_speculatively_success(self):
        """Test successful speculative merge check."""
        can_merge, reason = self.merger.can_merge_speculatively("100", "abc123")
        self.assertTrue(can_merge)
        self.assertIsNone(reason)
    
    def test_store_and_get_merge_base(self):
        """Test storing and retrieving merge base."""
        self.merger.store_merge_base("100", "abc123def456", ["99"])
        
        base_info = self.merger.get_merge_base("100")
        self.assertIsNotNone(base_info)
        self.assertEqual(base_info['hash'], "abc123def456")
        self.assertEqual(base_info['applied_changes'], ["99"])
    
    def test_handle_rebase_needed_success(self):
        """Test successful rebase when base changes."""
        success, reason = self.merger.handle_rebase_needed(
            change_id="100",
            new_base_hash="new_xyz789",
            old_base_hash="old_abc123"
        )
        
        self.assertTrue(success)
        self.assertIsNone(reason)
    
    def test_handle_rebase_same_base(self):
        """Test no rebase needed when base unchanged."""
        success, reason = self.merger.handle_rebase_needed(
            change_id="100",
            new_base_hash="abc123",
            old_base_hash="abc123"
        )
        
        self.assertTrue(success)


class TestGateAlgorithm(unittest.TestCase):
    """Test GateAlgorithm orchestration."""
    
    def setUp(self):
        self.redis = MockRedis()
        self.gerrit_conn = Mock()
        self.algorithm = GateAlgorithm(self.redis, self.gerrit_conn)
        
        # Mock git operations
        self.gerrit_conn.getRefHeadCommit = Mock(return_value="main_abc123")
    
    def test_enqueue_change(self):
        """Test enqueueing a change."""
        position = self.algorithm.enqueue_change(
            change_id="100",
            project_name="test-project",
            branch="main"
        )
        
        self.assertEqual(position, 0)
        
        # Verify stored in dependencies
        dep_data = self.redis.get_state("torri:change:100:dependencies")
        self.assertIsNotNone(dep_data)
        
        # Verify enqueued in redis
        queue = self.redis.queue_list_all("torri:pipeline:gate:queue")
        self.assertIn("100", queue)
    
    def test_enqueue_multiple_changes(self):
        """Test enqueueing multiple changes in order."""
        pos1 = self.algorithm.enqueue_change("100", "test", "main")
        pos2 = self.algorithm.enqueue_change("101", "test", "main")
        pos3 = self.algorithm.enqueue_change("102", "test", "main")
        
        self.assertEqual(pos1, 0)
        self.assertEqual(pos2, 1)
        self.assertEqual(pos3, 2)
    
    def test_start_speculative_testing(self):
        """Test starting speculative testing."""
        # Enqueue first
        self.algorithm.enqueue_change("100", "test", "main")
        
        # Start testing
        can_test, reason = self.algorithm.start_speculative_testing("100")
        
        self.assertTrue(can_test)
        self.assertIsNone(reason)
        
        # Verify state changed to TESTING
        state = self.redis.get_state("torri:change:100:state")
        self.assertEqual(state['status'], 'TESTING')
    
    def test_handle_test_success(self):
        """Test handling successful test result."""
        self.algorithm.enqueue_change("100", "test", "main")
        self.algorithm.start_speculative_testing("100")
        
        success = self.algorithm.handle_test_success("100")
        self.assertTrue(success)
        
        state = self.redis.get_state("torri:change:100:state")
        self.assertEqual(state['status'], 'MERGE_READY')
    
    def test_handle_test_failure(self):
        """Test handling test failure and cascading."""
        # Setup: Change 100 with dependent 101
        self.algorithm.enqueue_change("100", "test", "main")
        self.algorithm.enqueue_change("101", "test", "main")
        
        # Mark 101 as dependent on 100
        self.algorithm.dependencies.set_dependencies("100", ["101"])
        
        # Mark 101 as testing
        self.redis.set_state("torri:change:101:state", {"status": "TESTING"})
        
        # 100 fails
        affected = self.algorithm.handle_test_failure("100", "merge conflict")
        
        self.assertEqual(len(affected), 1)
        self.assertIn("101", affected)
        
        # Verify 100 marked as FAILED
        state = self.redis.get_state("torri:change:100:state")
        self.assertEqual(state['status'], 'FAILED')
    
    def test_process_queue_dequeues_when_space_available(self):
        """Test queue processing fills available window slots."""
        # Enqueue changes
        self.algorithm.enqueue_change("100", "test", "main")
        self.algorithm.enqueue_change("101", "test", "main")
        
        # Initialize window
        self.redis.set_state("torri:pipeline:gate:window", {
            'size': 5,
            'active': 0,
        })
        
        # Process queue
        started = self.algorithm.process_queue("gate", window_size=5)
        
        # Should dequeue and start at least one
        self.assertGreater(len(started), 0)
    
    def test_attempt_merge_with_validation(self):
        """Test merge attempt with validation."""
        # Setup
        self.algorithm.enqueue_change("100", "test", "main")
        self.algorithm.start_speculative_testing("100")
        self.algorithm.handle_test_success("100")
        
        # Mock gerrit change
        gerrit_change = {
            'labels': {'Code-Review': {'value': 1}},
            'mergeable': True,
            'status': 'NEW'
        }
        
        # Attempt merge
        success, reason = self.algorithm.attempt_merge("100", gerrit_change)
        
        # In MVP, merge should succeed (no actual git operations)
        self.assertTrue(success)
        
        # Verify state changed to MERGED
        state = self.redis.get_state("torri:change:100:state")
        self.assertEqual(state['status'], 'MERGED')
    
    def test_handle_merge_conflict(self):
        """Test handling merge conflict with rebase."""
        self.algorithm.enqueue_change("100", "test", "main")
        
        # Simulate main branch changed
        success, reason = self.algorithm.handle_merge_conflict(
            change_id="100",
            old_merge_base="old_abc123",
            new_merge_base="new_xyz789"
        )
        
        self.assertTrue(success)


class TestGateAlgorithmIntegration(unittest.TestCase):
    """Integration tests for complete Gate algorithm flow."""
    
    def setUp(self):
        self.redis = MockRedis()
        self.gerrit_conn = Mock()
        self.algorithm = GateAlgorithm(self.redis, self.gerrit_conn)
        self.gerrit_conn.getRefHeadCommit = Mock(return_value="main_abc123")
    
    def test_complete_flow_single_change(self):
        """Test complete flow for a single change."""
        # 1. Enqueue
        pos = self.algorithm.enqueue_change("100", "test", "main")
        self.assertEqual(pos, 0)
        
        # 2. Start testing
        can_test, _ = self.algorithm.start_speculative_testing("100")
        self.assertTrue(can_test)
        
        # 3. Test passes
        self.algorithm.handle_test_success("100")
        
        # 4. Attempt merge
        gerrit_change = {
            'labels': {'Code-Review': {'value': 1}},
            'mergeable': True,
        }
        success, _ = self.algorithm.attempt_merge("100", gerrit_change)
        self.assertTrue(success)
        
        # 5. Verify final state
        state = self.redis.get_state("torri:change:100:state")
        self.assertEqual(state['status'], 'MERGED')
    
    def test_complete_flow_multiple_changes_with_cascade(self):
        """Test flow with multiple changes and failure cascade."""
        # 1. Enqueue two changes
        self.algorithm.enqueue_change("100", "test", "main")
        self.algorithm.enqueue_change("101", "test", "main")
        
        # 2. Mark dependency (100's dependent is 101)
        self.algorithm.dependencies.set_dependencies("100", ["101"])
        
        # 3. Start testing both
        self.algorithm.start_speculative_testing("100")
        self.algorithm.start_speculative_testing("101")
        
        # 4. Change 100 fails
        affected = self.algorithm.handle_test_failure("100", "test failure")
        
        # 5. Change 101 should be affected
        self.assertEqual(len(affected), 1)
        self.assertIn("101", affected)
        
        # 6. Verify both states
        state_100 = self.redis.get_state("torri:change:100:state")
        state_101 = self.redis.get_state("torri:change:101:state")
        
        self.assertEqual(state_100['status'], 'FAILED')
        self.assertEqual(state_101['status'], 'requeue_needed')


if __name__ == '__main__':
    unittest.main(verbosity=2)
