"""
Pipeline management for Torri scheduler.

Two manager types, set via the 'manager' field in pipelines.yaml:
- independent: each change is tested on its own, no merge (e.g. check)
- dependent:   changes are tested speculatively and merged in order (e.g. gate)
"""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from abc import ABC, abstractmethod

from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedis, REDIS_KEYS
from torri.scheduler.gate_algorithm import GateAlgorithm


class BuildSetStatus(str, Enum):
    """Status of a build attempt."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"


class JobStatus(str, Enum):
    """Status of a single job."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    TIMEOUT = "timeout"


class BuildSetModel:
    """In-memory representation of a build attempt."""
    
    def __init__(self, change_id: str, pipeline_id: str, attempt: int = 1):
        self.buildset_id = str(uuid.uuid4())
        self.change_id = change_id
        self.pipeline_id = pipeline_id
        self.attempt = attempt
        self.status = BuildSetStatus.PENDING
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.started_at: Optional[datetime] = None
        self.ended_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            'buildset_id': self.buildset_id,
            'change_id': self.change_id,
            'pipeline_id': self.pipeline_id,
            'attempt': self.attempt,
            'status': self.status.value,
            'jobs': self.jobs,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
        }


class BasePipelineManager(ABC):
    """
    Abstract base class for pipeline managers.
    
    Manages queues, windows, and change state.
    """
    
    def __init__(self, pipeline_id: str, redis_client: TorriRedis, config=None, source=None):
        self.logger = get_logger(f"torri.scheduler.pipeline.{pipeline_id}")
        self.pipeline_id = pipeline_id
        self.redis = redis_client
        self.config = config
        self.source = source
        self.active_builds: Dict[str, BuildSetModel] = {}
    
    @abstractmethod
    def on_event(self, event_data: Dict[str, Any]):
        """Handle events for this pipeline."""
        pass
    
    @abstractmethod
    def should_merge(self) -> bool:
        """Whether this pipeline type can trigger merges."""
        pass
    
    def enqueue_change(self, change_id: str) -> int:
        """Add change to pipeline queue."""
        try:
            queue_key = REDIS_KEYS['pipeline_queue'].format(pipeline_id=self.pipeline_id)
            length = self.redis.queue_enqueue(queue_key, change_id)
            self.logger.info(
                "Enqueued change %s to pipeline %s, position=%d",
                change_id, self.pipeline_id, length
            )
            return length
        except Exception as e:
            self.logger.error("Error enqueueing change: %s", e)
            return 0
    
    def dequeue_change(self) -> Optional[str]:
        """Remove next change from queue."""
        try:
            queue_key = REDIS_KEYS['pipeline_queue'].format(pipeline_id=self.pipeline_id)
            change_id = self.redis.queue_dequeue(queue_key)
            if change_id:
                self.logger.info("Dequeued change %s from pipeline %s",
                               change_id, self.pipeline_id)
            return change_id
        except Exception as e:
            self.logger.error("Error dequeueing change: %s", e)
            return None
    
    def get_queue_length(self) -> int:
        """Get current queue length."""
        try:
            queue_key = REDIS_KEYS['pipeline_queue'].format(pipeline_id=self.pipeline_id)
            return self.redis.queue_length(queue_key)
        except Exception as e:
            self.logger.error("Error getting queue length: %s", e)
            return 0
    
    def get_queue_items(self) -> List[str]:
        """Get all items currently in queue."""
        try:
            queue_key = REDIS_KEYS['pipeline_queue'].format(pipeline_id=self.pipeline_id)
            return self.redis.queue_list_all(queue_key)
        except Exception as e:
            self.logger.error("Error listing queue items: %s", e)
            return []
    
    def get_window_size(self) -> int:
        """Get maximum concurrent changes in window."""
        try:
            window_key = REDIS_KEYS['pipeline_window'].format(pipeline_id=self.pipeline_id)
            window_data = self.redis.get_state(window_key)
            if window_data:
                return window_data.get('size', 1)
            return 1
        except Exception as e:
            self.logger.error("Error getting window size: %s", e)
            return 1
    
    def get_active_count(self) -> int:
        """Get number of changes currently being processed."""
        try:
            window_key = REDIS_KEYS['pipeline_window'].format(pipeline_id=self.pipeline_id)
            window_data = self.redis.get_state(window_key)
            if window_data:
                return window_data.get('active', 0)
            return 0
        except Exception as e:
            self.logger.error("Error getting active count: %s", e)
            return 0
    
    def update_window(self, size: int, active: int):
        """Update window state."""
        try:
            window_key = REDIS_KEYS['pipeline_window'].format(pipeline_id=self.pipeline_id)
            window_data = {
                'size': size,
                'active': active,
                'updated_at': datetime.utcnow().isoformat(),
            }
            self.redis.set_state(window_key, window_data)
        except Exception as e:
            self.logger.error("Error updating window: %s", e)
    
    def can_dequeue(self) -> bool:
        """Check if we can dequeue and start processing."""
        try:
            window_size = self.get_window_size()
            active_count = self.get_active_count()
            can_process = active_count < window_size
            self.logger.debug(
                "Window check for %s: active=%d, size=%d, can_dequeue=%s",
                self.pipeline_id, active_count, window_size, can_process
            )
            return can_process
        except Exception as e:
            self.logger.error("Error checking if can dequeue: %s", e)
            return False
    
    def create_buildset(self, change_id: str, attempt: int = 1) -> BuildSetModel:
        """Create new build set (attempt to process change)."""
        try:
            buildset = BuildSetModel(change_id, self.pipeline_id, attempt)
            buildset.started_at = datetime.utcnow()
            self.active_builds[buildset.buildset_id] = buildset
            
            buildset_key = REDIS_KEYS['buildset_state'].format(buildset_id=buildset.buildset_id)
            self.redis.set_state(buildset_key, buildset.to_dict())
            
            self.logger.info(
                "Created buildset %s for change %s (attempt %d)",
                buildset.buildset_id, change_id, attempt
            )
            return buildset
        except Exception as e:
            self.logger.error("Error creating buildset: %s", e)
            raise
    
    def get_buildset(self, buildset_id: str) -> Optional[BuildSetModel]:
        """Retrieve buildset from storage."""
        try:
            if buildset_id in self.active_builds:
                return self.active_builds[buildset_id]
            
            buildset_key = REDIS_KEYS['buildset_state'].format(buildset_id=buildset_id)
            buildset_data = self.redis.get_state(buildset_key)
            if not buildset_data:
                return None
            
            buildset = BuildSetModel(
                buildset_data['change_id'],
                buildset_data['pipeline_id'],
                buildset_data['attempt']
            )
            buildset.buildset_id = buildset_data['buildset_id']
            buildset.status = BuildSetStatus[buildset_data['status'].upper()]
            buildset.jobs = buildset_data.get('jobs', {})
            return buildset
        except Exception as e:
            self.logger.error("Error getting buildset: %s", e)
            return None

    def is_change_in_pipeline(self, change_number : str):
        queue_key = f"torri:pipeline:{self.pipeline_id}:queue"
        change_ids = self.redis.queue_list_all(queue_key)
        if change_number in change_ids:
            return True
        return False

    def update_buildset_status(self, buildset_id: str, status: BuildSetStatus):
        """Update buildset status."""
        try:
            buildset_key = REDIS_KEYS['buildset_state'].format(buildset_id=buildset_id)
            self.redis.update_state(buildset_key, {'status': status.value})
            self.logger.debug("Updated buildset %s status to %s", buildset_id, status)
        except Exception as e:
            self.logger.error("Error updating buildset status: %s", e)
    
class IndependentPipeline(BasePipelineManager):
    """
    Independent pipeline: each change is tested on its own, no merge.
    Maps to manager: independent in pipelines.yaml.
    """
    
    def on_event(self, event_data: Dict[str, Any]):
        """Handle independent pipeline events."""
        self.logger.debug("Independent pipeline event: %s", event_data)
    
    def should_merge(self) -> bool:
        return False


class DependentPipeline(BasePipelineManager):
    """
    Dependent pipeline: changes are tested speculatively on top of each other
    and merged in order when all jobs pass.
    Maps to manager: dependent in pipelines.yaml.
    
    Uses GateAlgorithm for:
    - Speculative merge base calculation
    - Ordered, dependent execution
    - Merge conflict handling
    - Cascade failure propagation
    """
    
    def __init__(self, pipeline_id: str, redis_client: TorriRedis, config=None, source=None):
        super().__init__(pipeline_id, redis_client, config=config, source=source)
        if source:
            self.gate_algorithm = GateAlgorithm(redis_client, source)
        else:
            self.gate_algorithm = None
    
    def on_event(self, event_data: Dict[str, Any]):
        """Handle dependent pipeline events."""
        self.logger.debug("Dependent pipeline event: %s", event_data)
    
    def should_merge(self) -> bool:
        return True
    
    def enqueue_change(self, change_id: str, project_name: str = None, branch: str = None) -> int:
        """
        Enqueue change using GateAlgorithm if available.
        Falls back to basic enqueue if algorithm not initialized.
        """
        try:
            if self.gate_algorithm and project_name and branch:
                try:
                    position = self.gate_algorithm.enqueue_change(change_id, project_name, branch)
                except Exception as e:
                    self.logger.error("Gate algorithm enqueue failed, falling back to basic enqueue: %s", e)
                    queue_key = REDIS_KEYS['pipeline_queue'].format(pipeline_id=self.pipeline_id)
                    position = self.redis.queue_enqueue(queue_key, change_id)
            else:
                # Fall back to basic enqueue
                queue_key = REDIS_KEYS['pipeline_queue'].format(pipeline_id=self.pipeline_id)
                position = self.redis.queue_enqueue(queue_key, change_id)
            
            self.logger.info(
                "Enqueued change %s to gate pipeline, position=%d",
                change_id, position
            )
            return position
        except Exception as e:
            self.logger.error("Error enqueueing change: %s", e)
            return 0
    
    def start_speculative_testing(self, change_id: str) -> bool:
        """Start speculative testing with merge base."""
        if not self.gate_algorithm:
            self.logger.warning("Gate algorithm not initialized, skipping speculative testing")
            return True  # Continue anyway
        
        try:
            can_test, reason = self.gate_algorithm.start_speculative_testing(change_id)
            return can_test
        except Exception as e:
            self.logger.error("Error starting speculative testing: %s", e)
            return False
    
    def mark_test_success(self, change_id: str) -> bool:
        """Mark change tests as passed, ready for merge."""
        if not self.gate_algorithm:
            return True
        
        try:
            return self.gate_algorithm.handle_test_success(change_id)
        except Exception as e:
            self.logger.error("Error marking test success: %s", e)
            return False
    
    def mark_test_failure(self, change_id: str, reason: str) -> List[str]:
        """
        Mark change tests as failed.
        Returns list of affected (dependent) changes.
        """
        if not self.gate_algorithm:
            return []
        
        try:
            return self.gate_algorithm.handle_test_failure(change_id, reason)
        except Exception as e:
            self.logger.error("Error marking test failure: %s", e)
            return []
    
    def attempt_merge(self, change_id: str, gerrit_change: Dict[str, Any]) -> bool:
        """Attempt to merge change if ready."""
        if not self.gate_algorithm:
            self.logger.warning("Gate algorithm not initialized, cannot merge")
            return False
        
        try:
            success, reason = self.gate_algorithm.attempt_merge(change_id, gerrit_change)
            if not success:
                self.logger.warning("Merge failed for %s: %s", change_id, reason)
            return success
        except Exception as e:
            self.logger.error("Error attempting merge: %s", e)
            return False
    
    def handle_merge_conflict(
        self,
        change_id: str,
        old_base: str,
        new_base: str
    ) -> bool:
        """Handle merge conflict by rebasing and restarting tests."""
        if not self.gate_algorithm:
            return False
        
        try:
            success, reason = self.gate_algorithm.handle_merge_conflict(
                change_id, old_base, new_base
            )
            return success
        except Exception as e:
            self.logger.error("Error handling merge conflict: %s", e)
            return False


def create_pipeline(pipeline_type: str, pipeline_id: str, redis_client: TorriRedis, source=None) -> BasePipelineManager:
    """Factory to create pipeline based on the manager field from pipelines.yaml."""
    if pipeline_type.lower() == "independent":
        return IndependentPipeline(pipeline_id, redis_client)
    elif pipeline_type.lower() == "dependent":
        return DependentPipeline(pipeline_id, redis_client, source=source)
    else:
        raise ValueError(f"Unknown pipeline manager type: {pipeline_type}")
