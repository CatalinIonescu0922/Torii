"""
Redis client for scheduler state management.
Handles locks, queues, and change/buildset tracking.
Simple sync client following torri patterns.
"""

import os
import json
import pickle
import redis
from typing import Optional, Dict, Any, List
from datetime import datetime
from shared.logger_setup import get_logger


class TorriRedis:
    """
    Thread-safe Redis wrapper for state operations.
    Used by scheduler to store changes, buildsets, and locks.
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.logger = get_logger("torri.scheduler.redis")
        url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.client = redis.from_url(url, decode_responses=True)
        # Separate client for binary (pickle) data — decode_responses must be False
        self._binary_client = redis.from_url(url, decode_responses=False)
        
        try:
            self.client.ping()
            self.logger.info("Connected to Redis")
        except Exception as e:
            self.logger.error("Failed to connect to Redis: %s", e, exc_info=True)
            raise
    
    def acquire_lock(self, lock_key: str, timeout: int = 30) -> bool:
        """Acquire distributed lock with timeout."""
        try:
            result = self.client.set(
                lock_key,
                datetime.utcnow().isoformat(),
                nx=True,
                ex=timeout
            )
            if result:
                self.logger.debug("Acquired lock: %s", lock_key)
            return result is not None
        except Exception as e:
            self.logger.error("Error acquiring lock %s: %s", lock_key, e)
            return False
    
    def release_lock(self, lock_key: str) -> bool:
        """Release distributed lock."""
        try:
            result = self.client.delete(lock_key)
            if result > 0:
                self.logger.debug("Released lock: %s", lock_key)
            return result > 0
        except Exception as e:
            self.logger.error("Error releasing lock %s: %s", lock_key, e)
            return False
    
    def queue_enqueue(self, queue_key: str, item_id: str) -> int:
        """Enqueue item to pipeline queue. Idempotent — skips if already present."""
        try:
            existing_pos = self.client.lpos(queue_key, item_id)
            if existing_pos is not None:
                self.logger.debug("Skip duplicate enqueue %s in %s at pos=%d", item_id, queue_key, existing_pos)
                return existing_pos + 1
            length = self.client.rpush(queue_key, item_id)
            self.logger.debug("Enqueued %s to %s, length: %d", item_id, queue_key, length)
            return length
        except Exception as e:
            self.logger.error("Error enqueueing to %s: %s", queue_key, e)
            raise
    
    def queue_dequeue(self, queue_key: str) -> Optional[str]:
        """Dequeue item from pipeline queue."""
        try:
            item = self.client.lpop(queue_key)
            if item:
                self.logger.debug("Dequeued %s from %s", item, queue_key)
            return item
        except Exception as e:
            self.logger.error("Error dequeueing from %s: %s", queue_key, e)
            raise
    
    def queue_length(self, queue_key: str) -> int:
        """Get queue length."""
        try:
            return self.client.llen(queue_key)
        except Exception as e:
            self.logger.error("Error getting queue length for %s: %s", queue_key, e)
            return 0
    
    def queue_peek(self, queue_key: str, index: int = 0) -> Optional[str]:
        """Peek at queue item without removing."""
        try:
            return self.client.lindex(queue_key, index)
        except Exception as e:
            self.logger.error("Error peeking queue %s: %s", queue_key, e)
            return None
    
    def queue_list_all(self, queue_key: str) -> List[str]:
        """Get all queue items."""
        try:
            items = self.client.lrange(queue_key, 0, -1)
            return items or []
        except Exception as e:
            self.logger.error("Error listing queue %s: %s", queue_key, e)
            return []
    
    def set_state(self, state_key: str, state_data: Dict[str, Any], ttl: Optional[int] = None) -> bool:
        """Store state as JSON in Redis."""
        try:
            json_data = json.dumps(state_data)
            if ttl:
                self.client.setex(state_key, ttl, json_data)
            else:
                self.client.set(state_key, json_data)
            self.logger.debug("Set state for %s", state_key)
            return True
        except Exception as e:
            self.logger.error("Error setting state for %s: %s", state_key, e)
            return False
    
    def get_state(self, state_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve state as dictionary from Redis."""
        try:
            json_data = self.client.get(state_key)
            if json_data:
                return json.loads(json_data)
            return None
        except Exception as e:
            self.logger.error("Error getting state for %s: %s", state_key, e)
            return None
    
    def update_state(self, state_key: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Merge updates into existing state."""
        try:
            current_state = self.get_state(state_key) or {}
            current_state.update(updates)
            self.set_state(state_key, current_state)
            return current_state
        except Exception as e:
            self.logger.error("Error updating state for %s: %s", state_key, e)
            return None
    
    def publish_event(self, channel: str, message: Dict[str, Any]) -> int:
        """Publish event to Redis Pub/Sub channel."""
        try:
            json_message = json.dumps(message)
            subscribers = self.client.publish(channel, json_message)
            self.logger.debug("Published to %s, %d subscribers", channel, subscribers)
            return subscribers
        except Exception as e:
            self.logger.error("Error publishing to %s: %s", channel, e)
            return 0
    
    def increment(self, key: str, amount: int = 1) -> int:
        """Increment counter."""
        try:
            return self.client.incrby(key, amount)
        except Exception as e:
            self.logger.error("Error incrementing %s: %s", key, e)
            return 0
    
    def get_integer(self, key: str) -> int:
        """Get integer value."""
        try:
            value = self.client.get(key)
            return int(value) if value else 0
        except Exception as e:
            self.logger.error("Error getting integer %s: %s", key, e)
            return 0
    
    def delete(self, key: str) -> bool:
        """Delete key."""
        try:
            result = self.client.delete(key)
            return result > 0
        except Exception as e:
            self.logger.error("Error deleting %s: %s", key, e)
            return False
    
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        try:
            result = self.client.exists(key)
            return result > 0
        except Exception as e:
            self.logger.error("Error checking existence of %s: %s", key, e)
            return False

    # 7 days — long enough to survive a weekend; short enough to self-clean stale data
    _CHANGE_TTL = 7 * 24 * 60 * 60

    def store_change(self, change_number, patchset, change) -> None:
        """
        Persist a GerritChange object to Redis using pickle.

        Stored under two keys:
          torri:change:{number}:{patchset}  — versioned, precise lookup
          torri:change:{number}             — always the latest patchset
        """
        data = pickle.dumps(change)
        versioned_key = f"torri:change:{change_number}:{patchset}"
        latest_key = f"torri:change:{change_number}"
        self._binary_client.setex(versioned_key, self._CHANGE_TTL, data)
        self._binary_client.setex(latest_key, self._CHANGE_TTL, data)

    def get_change(self, change_number, patchset=None):
        """
        Retrieve a GerritChange object from Redis.

        When patchset is given, reads the versioned key.
        When patchset is None, reads the latest-patchset key.
        Returns None when the change is not cached.
        """
        key = (
            f"torri:change:{change_number}:{patchset}"
            if patchset is not None
            else f"torri:change:{change_number}"
        )
        data = self._binary_client.get(key)
        if data is None:
            return None
        return pickle.loads(data)


# Redis key naming patterns (const patterns)
REDIS_KEYS = {
    'pipeline_queue': 'torri:pipeline:{pipeline_id}:queue',
    'pipeline_window': 'torri:pipeline:{pipeline_id}:window',
    'change_state': 'torri:change:{change_id}:state',
    'buildset_state': 'torri:buildset:{buildset_id}:state',
    'job_state': 'torri:job:{job_id}:state',
    'job_logs': 'torri:job:{job_id}:logs',
    'lock_pipeline': 'torri:lock:pipeline:{pipeline_id}',
    'lock_merge': 'torri:lock:global:merge',
    'event_queue': 'torri:event-queue',
}


def get_redis_key(pattern: str, **kwargs) -> str:
    """
    Helper to get Redis key with variable substitution.
    
    Example:
        get_redis_key(REDIS_KEYS['pipeline_queue'], pipeline_id='check')
    """
    return pattern.format(**kwargs)
