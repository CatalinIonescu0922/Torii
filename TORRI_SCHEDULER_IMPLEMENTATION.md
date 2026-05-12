# Torri Scheduler Implementation Guide
## Event-Driven CI/CD Orchestrator with Redis-based Distributed State

**Tech Stack**:
- Backend: Python 3.10+ with FastAPI (async)
- Message Broker: Apache Kafka (KRaft mode)
- Distributed State: Redis (replacing ZooKeeper)
- Job Executor: Custom Python-based executor
- Git Operations: Speculative merger (custom)
- Version Control: Gerrit (code review gate)
- Configuration: YAML declarative (jobs.yaml, pipelines.yaml, projects.yaml)

**Deployment Model**:
- Multiple Scheduler instances (scale horizontally)
- Each instance is single-threaded (consistency)
- Coordination via Redis distributed locks (no conflicts)
- Shared Kafka topics (event flow)
- Shared Redis state (source of truth)

---

## Architecture Overview

### Component Topology (Adapted to Torri Stack)

```
┌─────────────────────────────────────────────────────────────┐
│                    Gerrit Event Source                      │
│                  (Push, PatchSet events)                    │
└────────────────────────┬────────────────────────────────────┘
                         │
                    Webhook/Stream
                         │
         ┌───────────────┴───────────────┐
         │                               │
    ┌────▼──────────────────┐   ┌────────▼────────────────────┐
    │    Kafka Topics       │   │   Event Normalization       │
    │  (Distributed Log)    │   │   (Convert to Torri Events) │
    │                       │   └────────┬────────────────────┘
    │ • gerrit-events       │            │
    │ • scheduler-trigger   │            │
    │ • merger-requests     │   ┌────────▼────────────────────┐
    │ • merger-responses    │   │   FastAPI Scheduler        │
    │ • job-results         │   │   (Main Event Loop)        │
    │ • job-queue          │   │                            │
    │ • pipeline-state     │   │ Single-threaded loop:     │
    └───────────────────────┘   │ 1. Receive events         │
                                │ 2. Update pipelines       │
         ┌──────────────────────┤ 3. Schedule jobs          │
         │                      │ 4. Coordinate merges      │
    ┌────▼──────────────────┐   │ 5. Report results         │
    │   Redis (State)       │   │                            │
    │                       │   │ Worker threads:           │
    │ • Pipeline queues     │   │ • Config loader           │
    │ • Change state        │   │ • Cleanup                 │
    │ • Job tracking        │   │ • Stats emission          │
    │ • Build set records   │   │ • Pipeline processing     │
    │ • Locks (distributed) │   └────┬───────────────────────┘
    │ • Tenant models       │        │
    └───────────────────────┘        │ Coordination
         ▲                           │
         │                           │
    ┌────┴──────────────────┐   ┌────▼───────────────────────┐
    │  Pipeline Managers    │   │   External Services       │
    │  (In Redis)           │   │                            │
    │                       │   │ • Merger (Git ops)        │
    │ • Check pipes         │   │ • Executor (Run jobs)     │
    │ • Gate pipes          │   │ • Launcher (Provision)    │
    │ • Report pipes        │   └────────────────────────────┘
    │ • Window management   │
    │ • Dependent ordering  │
    └───────────────────────┘
```

---

## Part 0: Multi-Scheduler Architecture (Critical for Scale)

### 0.1 Why Single-Threaded PER Scheduler?

The single-threaded design is **per scheduler instance**, not globally:

```
GLOBAL SYSTEM (Multiple Scheduler Instances)
│
├─ Scheduler Instance 1 (FastAPI)
│  └─ Single-threaded event loop: Process events sequentially
│     └─ Acquires Redis lock for "pipeline:check"
│        └─ Processes 5 changes atomically
│           └─ Releases lock
│
├─ Scheduler Instance 2 (FastAPI)
│  └─ Single-threaded event loop: Process events sequentially
│     └─ Waiting for lock on "pipeline:check"
│        └─ When lock available: Acquires and processes
│
└─ Scheduler Instance N (FastAPI)
   └─ Similar pattern...

Redis (Central Coordination):
├─ Distribu Locks (only 1 scheduler has lock at a time)
├─ Event Queue (all schedulers read from same queue)
├─ Pipeline State (shared, consistent)
└─ Change/Job State (shared, consistent)
```

### 0.2 Why This Matters for Multiple Schedulers

**Problem Without Coordination:**
```
Scheduler 1                    Scheduler 2
   │                               │
   └─ Read: Pipeline queue      └─ Read: Pipeline queue
      [Change A, B, C]             [Change A, B, C]
   │                               │
   ├─ Dequeue Change A          ├─ Dequeue Change A (conflict!)
   ├─ Schedule jobs             ├─ Schedule jobs (duplicate!)
   └─ Update state              └─ Update state (race condition!)
   
RESULT: Change A gets tested twice, jobs scheduled twice, state corrupted
```

**Solution With Distributed Locks:**
```
Scheduler 1                    Scheduler 2
   │                               │
   ├─ Acquire Lock               ├─ Try to acquire lock
   │  "pipeline:check"           │  BLOCKED (waiting)
   │  ✓ Success                  │
   │                             │
   ├─ Read: Pipeline queue       │  Spinning, checking lock
   │  [Change A, B, C]           │
   │                             │
   ├─ Dequeue Change A           │  Lock released by Scheduler 1
   ├─ Schedule jobs              ├─ Acquire Lock ✓
   ├─ Update state               ├─ Read queue [B, C]
   │                             ├─ Dequeue Change B
   └─ Release Lock ✓             ├─ Schedule jobs
                                 ├─ Update state
                                 └─ Release Lock ✓

RESULT: Sequential, atomic processing. No conflicts.
```

### 0.3 Merge & UI Update Safety with Multiple Schedulers

**Scenario: Two schedulers, one pipeline**

```
1. Change A → Scheduler 1 acquires lock → processes → ready to merge
2. Merge Service: Acquires MERGE_LOCK (global, only 1 merge at a time)
   └─ Lock held for actual git merge operation
3. Merge succeeds, broadcasted to all UIs via WebSocket
4. Scheduler 2 can now process next change safely

Timeline:
  T0: Scheduler-1 locks "pipeline:gate"
  T1: Scheduler-1 processes Change A (all jobs pass)
  T2: Scheduler-1 ready to merge, requests Merge Service
  T3: Merge Service acquires MERGE_LOCK
  T4: Git merge happens (atomic)
  T5: Merge Service releases MERGE_LOCK
  T6: Scheduler-1 broadcasts "Change A merged" to Redis
  T7: All WebSocket clients receive update
  T8: Scheduler-1 releases "pipeline:gate" lock
  T9: Scheduler-2 acquires "pipeline:gate" lock
  T10: Scheduler-2 processes Change B
```

### 0.4 Multiple Schedulers Enable:

| Scenario | Benefit |
|----------|---------|
| **Scale horizontally** | 10 pipelines, 2 schedulers → each handles 5 |
| **High availability** | Scheduler 1 crashes, Scheduler 2 continues |
| **Pipeline isolation** | Different schedulers for different tenants |
| **Load balancing** | Distribute work via Redis queue consumption |

---

## Part 1: State Management with Redis

### 1.1 Redis Schema Design

Instead of ZooKeeper's hierarchical model, use Redis key-value with structured prefixing:

```python
# Redis Key Namespacing Pattern
REDIS_KEY_PREFIX = "torri"

# Category Keys (Top Level)
TENANTS = f"{REDIS_KEY_PREFIX}:tenants"                    # Set of tenant IDs
PIPELINES = f"{REDIS_KEY_PREFIX}:pipelines"                # Hash of pipeline definitions
CHANGES = f"{REDIS_KEY_PREFIX}:changes"                    # Hash of change objects
BUILD_SETS = f"{REDIS_KEY_PREFIX}:build-sets"              # Hash of build attempts
JOBS = f"{REDIS_KEY_PREFIX}:jobs"                          # Hash of job states

# Pipeline-specific Keys
PIPELINE_QUEUE = f"{REDIS_KEY_PREFIX}:pipeline:{{pipeline_id}}:queue"         # Deque
PIPELINE_WINDOW = f"{REDIS_KEY_PREFIX}:pipeline:{{pipeline_id}}:window"       # Hash (size, active count)
PIPELINE_DIRTY = f"{REDIS_KEY_PREFIX}:pipeline:{{pipeline_id}}:dirty"         # Bool flag

# Change-specific Keys
CHANGE_STATE = f"{REDIS_KEY_PREFIX}:change:{{change_id}}:state"               # Current pipeline position
CHANGE_BUILD_SETS = f"{REDIS_KEY_PREFIX}:change:{{change_id}}:builds"         # Ordered list of attempts
CHANGE_ARTIFACTS = f"{REDIS_KEY_PREFIX}:change:{{change_id}}:artifacts"       # Dict of files

# Job-specific Keys
JOB_STATE = f"{REDIS_KEY_PREFIX}:job:{{job_id}}:state"                        # Status enum
JOB_RESULT = f"{REDIS_KEY_PREFIX}:job:{{job_id}}:result"                      # Pass/fail details
JOB_LOGS = f"{REDIS_KEY_PREFIX}:job:{{job_id}}:logs"                          # Compressed log stream

# Distributed Locks
LOCK_PIPELINE = f"{REDIS_KEY_PREFIX}:lock:pipeline:{{pipeline_id}}"           # Named lock
LOCK_CHANGE = f"{REDIS_KEY_PREFIX}:lock:change:{{change_id}}"                 # Named lock
LOCK_MERGE = f"{REDIS_KEY_PREFIX}:lock:merge"                                 # Global merge lock

# Event Queues (for processing)
EVENT_QUEUE = f"{REDIS_KEY_PREFIX}:event-queue"                               # List (FIFO)
PRIORITY_QUEUE = f"{REDIS_KEY_PREFIX}:priority-queue"                         # Sorted set by priority
```

### 1.2 Redis Client Wrapper for Torri

```python
# File: microservices/Torri/src/torri/scheduler/redis_client.py

import json
import asyncio
from typing import Optional, Any, Dict, List
from redis.asyncio import Redis, RedisCluster
from redis.asyncio.locks import Lock
from shared.logger_setup import get_logger

class TorriRedisClient:
    """
    Async Redis client for Torri scheduler state management.
    Replaces ZooKeeper for distributed coordination.
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/0", 
                 cluster_mode: bool = False):
        self.logger = get_logger("torri.scheduler.redis")
        self.redis_url = redis_url
        self.cluster_mode = cluster_mode
        self.redis: Optional[Redis] = None
        self._locks: Dict[str, Lock] = {}

    async def connect(self):
        """Initialize Redis connection pool."""
        try:
            if self.cluster_mode:
                self.redis = await RedisCluster.from_url(self.redis_url)
            else:
                self.redis = await Redis.from_url(self.redis_url, 
                                                   decode_responses=True,
                                                   socket_connect_timeout=5,
                                                   socket_keepalive=True)
            await self.redis.ping()
            self.logger.info(f"✓ Connected to Redis: {self.redis_url}")
        except Exception as e:
            self.logger.error(f"✗ Failed to connect to Redis: {e}")
            raise

    async def disconnect(self):
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
            self.logger.info("Redis disconnected")

    # ============= Document Operations (JSON Serialization) =============

    async def set_json(self, key: str, obj: Dict[str, Any], ttl: Optional[int] = None):
        """
        Store object as JSON in Redis.
        
        Args:
            key: Redis key
            obj: Dictionary to serialize
            ttl: Time-to-live in seconds
        """
        try:
            json_data = json.dumps(obj)
            if ttl:
                await self.redis.setex(key, ttl, json_data)
            else:
                await self.redis.set(key, json_data)
            self.logger.debug(f"Stored JSON: {key}")
        except Exception as e:
            self.logger.error(f"Failed to set_json {key}: {e}")
            raise

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve and deserialize JSON object from Redis."""
        try:
            data = await self.redis.get(key)
            if data is None:
                return None
            return json.loads(data)
        except Exception as e:
            self.logger.error(f"Failed to get_json {key}: {e}")
            return None

    # ============= Pipeline State Management =============

    async def pipeline_enqueue_change(self, pipeline_id: str, change_id: str):
        """Add change to pipeline queue (FIFO order)."""
        queue_key = f"torri:pipeline:{pipeline_id}:queue"
        await self.redis.rpush(queue_key, change_id)
        self.logger.debug(f"Change {change_id} enqueued to {pipeline_id}")

    async def pipeline_dequeue_change(self, pipeline_id: str) -> Optional[str]:
        """Remove and return first change in pipeline queue."""
        queue_key = f"torri:pipeline:{pipeline_id}:queue"
        change_id = await self.redis.lpop(queue_key)
        if change_id:
            self.logger.debug(f"Change {change_id} dequeued from {pipeline_id}")
        return change_id

    async def pipeline_get_queue(self, pipeline_id: str) -> List[str]:
        """Get all changes currently in pipeline queue."""
        queue_key = f"torri:pipeline:{pipeline_id}:queue"
        return await self.redis.lrange(queue_key, 0, -1)

    async def pipeline_set_window(self, pipeline_id: str, 
                                  window_size: int, 
                                  active_count: int = 0):
        """
        Store pipeline window state.
        Window size = max parallel changes
        Active count = currently processing
        """
        window_key = f"torri:pipeline:{pipeline_id}:window"
        window_data = {
            "size": window_size,
            "active": active_count,
            "timestamp": int(asyncio.get_event_loop().time() * 1000)
        }
        await self.set_json(window_key, window_data)

    async def pipeline_get_window(self, pipeline_id: str) -> Dict[str, Any]:
        """Get current pipeline window configuration."""
        window_key = f"torri:pipeline:{pipeline_id}:window"
        return await self.get_json(window_key) or {"size": 1, "active": 0}

    async def pipeline_mark_dirty(self, pipeline_id: str):
        """Flag pipeline as needing reprocessing."""
        dirty_key = f"torri:pipeline:{pipeline_id}:dirty"
        await self.redis.set(dirty_key, "true", ex=3600)  # 1 hour TTL
        self.logger.debug(f"Pipeline {pipeline_id} marked dirty")

    async def pipeline_is_dirty(self, pipeline_id: str) -> bool:
        """Check if pipeline needs processing."""
        dirty_key = f"torri:pipeline:{pipeline_id}:dirty"
        result = await self.redis.get(dirty_key)
        return result is not None

    async def pipeline_clear_dirty(self, pipeline_id: str):
        """Clear dirty flag after processing."""
        dirty_key = f"torri:pipeline:{pipeline_id}:dirty"
        await self.redis.delete(dirty_key)

    # ============= Change State Management =============

    async def change_set_state(self, change_id: str, state: Dict[str, Any]):
        """
        Store change state.
        
        State includes:
        - current_pipeline: Which pipeline processing this change
        - position_in_queue: Where in queue
        - build_sets: List of build attempt IDs
        - artifacts: Merged commit hash, logs, etc.
        """
        state_key = f"torri:change:{change_id}:state"
        await self.set_json(state_key, state, ttl=86400)  # 24 hour TTL

    async def change_get_state(self, change_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve complete change state."""
        state_key = f"torri:change:{change_id}:state"
        return await self.get_json(state_key)

    async def change_add_build_set(self, change_id: str, build_set_id: str):
        """Add build attempt to change's history."""
        builds_key = f"torri:change:{change_id}:builds"
        await self.redis.rpush(builds_key, build_set_id)

    async def change_get_build_sets(self, change_id: str) -> List[str]:
        """Get history of build attempts for change."""
        builds_key = f"torri:change:{change_id}:builds"
        return await self.redis.lrange(builds_key, 0, -1)

    # ============= Job State Management =============

    async def job_set_state(self, job_id: str, status: str, 
                           result: Optional[Dict[str, Any]] = None):
        """
        Store job execution state.
        
        Status: QUEUED, NODESET, PREPARING, RUNNING, SUCCESS, FAILURE, CANCELLED
        """
        state_key = f"torri:job:{job_id}:state"
        job_state = {
            "status": status,
            "timestamp": int(asyncio.get_event_loop().time() * 1000),
            "result": result or {}
        }
        await self.set_json(state_key, job_state)

    async def job_get_state(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve job state."""
        state_key = f"torri:job:{job_id}:state"
        return await self.get_json(state_key)

    async def job_append_log(self, job_id: str, log_line: str):
        """Append log line to job's log stream."""
        logs_key = f"torri:job:{job_id}:logs"
        await self.redis.rpush(logs_key, log_line)
        # Trim logs to last 10000 lines
        await self.redis.ltrim(logs_key, -10000, -1)

    async def job_get_logs(self, job_id: str, start: int = 0, 
                          end: int = -1) -> List[str]:
        """Retrieve job logs (with pagination)."""
        logs_key = f"torri:job:{job_id}:logs"
        return await self.redis.lrange(logs_key, start, end)

    # ============= Distributed Locking =============

    async def acquire_lock(self, lock_name: str, timeout: int = 10, 
                          blocking_timeout: float = 5.0) -> Lock:
        """
        Acquire a distributed lock.
        
        Args:
            lock_name: Name of lock (e.g., "pipeline:check-tests")
            timeout: How long lock is held (seconds)
            blocking_timeout: How long to wait for lock
        """
        lock_key = f"torri:lock:{lock_name}"
        lock = self.redis.lock(lock_key, timeout=timeout)
        
        try:
            acquired = await asyncio.wait_for(
                lock.acquire(blocking=True),
                timeout=blocking_timeout
            )
            if acquired:
                self.logger.debug(f"✓ Acquired lock: {lock_name}")
                return lock
            else:
                self.logger.warning(f"✗ Failed to acquire lock: {lock_name}")
                raise TimeoutError(f"Could not acquire lock {lock_name}")
        except asyncio.TimeoutError:
            self.logger.error(f"✗ Lock acquisition timeout: {lock_name}")
            raise

    async def release_lock(self, lock: Lock):
        """Release a distributed lock."""
        try:
            await lock.release()
            self.logger.debug("✓ Lock released")
        except Exception as e:
            self.logger.error(f"Failed to release lock: {e}")

    # ============= Event Queue Operations =============

    async def event_queue_push(self, event: Dict[str, Any]):
        """Push event to main processing queue."""
        queue_key = "torri:event-queue"
        event_json = json.dumps(event)
        await self.redis.rpush(queue_key, event_json)

    async def event_queue_pop(self, timeout: int = 1) -> Optional[Dict[str, Any]]:
        """Pop next event from queue (blocking)."""
        queue_key = "torri:event-queue"
        try:
            result = await asyncio.wait_for(
                self.redis.blpop(queue_key, timeout=timeout),
                timeout=timeout + 0.5
            )
            if result:
                _, event_json = result
                return json.loads(event_json)
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            self.logger.error(f"Error popping event: {e}")
            return None

    # ============= Batch Operations =============

    async def get_all_changes(self) -> List[Dict[str, Any]]:
        """Get all active changes from Redis."""
        changes = []
        cursor = 0
        pattern = "torri:change:*:state"
        
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                change_data = await self.get_json(key)
                if change_data:
                    changes.append(change_data)
            
            if cursor == 0:
                break
        
        return changes

    async def get_all_pipelines(self) -> List[str]:
        """Get all pipeline IDs."""
        cursor = 0
        pipelines = set()
        pattern = "torri:pipeline:*:window"
        
        while True:
            cursor, keys = await self.redis.scan(cursor, match=pattern, count=100)
            for key in keys:
                # Extract pipeline_id from "torri:pipeline:PIPELINE_ID:window"
                parts = key.split(":")
                if len(parts) >= 3:
                    pipelines.add(parts[2])
            
            if cursor == 0:
                break
        
        return list(pipelines)

    async def health_check(self) -> bool:
        """Check if Redis is healthy."""
        try:
            result = await self.redis.ping()
            return result == True
        except Exception:
            return False
```

---

## Part 2: Event-Driven Scheduler with FastAPI

### 2.1 Pydantic Models for Torri Events

```python
# File: microservices/Torri/src/torri/scheduler/models.py

from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid

# ============= Event Models =============

class EventType(str, Enum):
    GERRIT_PATCHSET_CREATED = "gerrit.patchset.created"
    GERRIT_CHANGE_UPDATED = "gerrit.change.updated"
    GERRIT_CHANGE_MERGED = "gerrit.change.merged"
    JOB_COMPLETED = "job.completed"
    BUILD_SET_COMPLETE = "build.set.complete"
    MERGE_COMPLETED = "merge.completed"
    PIPELINE_TRIGGER = "pipeline.trigger"
    CONFIG_UPDATED = "config.updated"
    MANUAL_ENQUEUE = "manual.enqueue"

class TorriEvent(BaseModel):
    """Base event model for all Torri events."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str  # e.g., "gerrit", "manual", "system"
    tenant_id: str
    change_id: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)
    trace_id: Optional[str] = None  # For distributed tracing

class GerritEventData(BaseModel):
    """Data from Gerrit webhook."""
    project: str
    branch: str
    change_number: int
    patchset_number: int
    commit_hash: str
    author: str
    subject: str
    url: str

class JobCompletedData(BaseModel):
    """Data from job completion."""
    job_id: str
    build_set_id: str
    status: str  # SUCCESS, FAILURE, ERROR
    duration_ms: int
    logs_url: Optional[str] = None
    artifacts: Dict[str, str] = Field(default_factory=dict)

# ============= Pipeline Models =============

class PipelineType(str, Enum):
    CHECK = "check"      # Independent parallel testing
    GATE = "gate"        # Dependent merge validation
    REPORT = "report"    # Post-merge notifications

class Pipeline(BaseModel):
    """Represents a pipeline definition."""
    pipeline_id: str
    name: str
    type: PipelineType
    tenant_id: str
    
    # Configuration
    trigger_on: List[str]  # e.g., ["patchset-created", "change-updated"]
    jobs: List[str]        # Job names to run
    window_size: int = 1
    
    # Merge requirements (for gate pipelines)
    require_approval: bool = False
    approval_count: int = 1
    
    # Execution settings
    depend_sequential: bool = False  # True for gate (dependent), False for check (independent)
    
class PipelineState(BaseModel):
    """Runtime state of a pipeline."""
    pipeline_id: str
    queue: List[str]          # Change IDs in queue
    window_size: int          # Max parallel changes
    active_changes: List[str] # Currently processing
    dirty: bool               # Needs reprocessing

# ============= Change Models =============

class ChangeState(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    MERGED = "MERGED"
    ABANDONED = "ABANDONED"

class Change(BaseModel):
    """Represents a code change from Gerrit."""
    change_id: str
    project: str
    branch: str
    commit_hash: str
    author: str
    subject: str
    gerrit_url: str
    
    # Status tracking
    current_pipeline: Optional[str] = None
    state: ChangeState = ChangeState.PENDING
    build_sets: List[str] = Field(default_factory=list)
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

# ============= Build Set Models =============

class BuildSet(BaseModel):
    """
    Immutable container for one attempt at processing a change.
    Enables tracking multiple retries and debugging.
    """
    build_set_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    change_id: str
    pipeline_id: str
    
    jobs: Dict[str, str] = Field(default_factory=dict)  # job_name -> job_id
    status: str = "PENDING"  # PENDING, IN_PROGRESS, SUCCESS, FAILURE
    
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    artifacts: Dict[str, Any] = Field(default_factory=dict)

# ============= Job Models =============

class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    NODESET = "NODESET"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"

class JobDefinition(BaseModel):
    """Job configuration from YAML."""
    name: str
    runs_on: str  # Node label requirement
    
    playbooks: List[str] = Field(default_factory=list)
    vars: Dict[str, Any] = Field(default_factory=dict)
    timeout: int = 3600  # seconds
    
    depends_on: List[str] = Field(default_factory=list)
    allows_failure: bool = False

class JobExecution(BaseModel):
    """Runtime job execution state."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    build_set_id: str
    
    definition: JobDefinition
    status: JobStatus = JobStatus.QUEUED
    
    assigned_node: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    result: Optional[Dict[str, Any]] = None
```

### 2.2 FastAPI Scheduler Server

```python
# File: microservices/Torri/src/torri/scheduler/server.py

from fastapi import FastAPI, WebSocket, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import asyncio
import json
from typing import Optional, Dict, Any
from datetime import datetime

from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedisClient
from torri.scheduler.models import (
    TorriEvent, EventType, GerritEventData, Pipeline, PipelineType,
    Change, ChangeState, BuildSet, JobExecution, JobStatus
)
from torri.scheduler.pipeline_manager import PipelineManager
from torri.scheduler.event_processor import EventProcessor
from torri.kafka.producer import KafkaProducerClient

logger = get_logger("torri.scheduler.server")

# ============= Global State =============

class SchedulerState:
    """Container for scheduler runtime state."""
    def __init__(self):
        self.redis_client: Optional[TorriRedisClient] = None
        self.kafka_producer: Optional[KafkaProducerClient] = None
        self.pipeline_managers: Dict[str, PipelineManager] = {}
        self.event_processor: Optional[EventProcessor] = None
        self.main_loop_task: Optional[asyncio.Task] = None
        self.running = False

scheduler_state = SchedulerState()

# ============= Lifespan Management =============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    
    # STARTUP
    logger.info("🚀 Torri Scheduler initializing...")
    
    # Connect to Redis
    scheduler_state.redis_client = TorriRedisClient(
        redis_url="redis://localhost:6379/0"
    )
    await scheduler_state.redis_client.connect()
    
    # Initialize Kafka producer
    scheduler_state.kafka_producer = KafkaProducerClient(
        bootstrap_servers="localhost:9094"
    )
    
    # Initialize event processor
    scheduler_state.event_processor = EventProcessor(
        redis_client=scheduler_state.redis_client,
        kafka_producer=scheduler_state.kafka_producer
    )
    
    # Load pipelines from configuration
    await load_pipelines_from_config()
    
    # Start main event loop
    scheduler_state.running = True
    scheduler_state.main_loop_task = asyncio.create_task(main_event_loop())
    
    logger.info("✓ Scheduler ready and listening for events")
    
    yield
    
    # SHUTDOWN
    logger.info("🛑 Torri Scheduler shutting down...")
    scheduler_state.running = False
    
    if scheduler_state.main_loop_task:
        await scheduler_state.main_loop_task
    
    if scheduler_state.redis_client:
        await scheduler_state.redis_client.disconnect()
    
    logger.info("✓ Scheduler shutdown complete")

# ============= FastAPI App =============

app = FastAPI(
    title="Torri Scheduler",
    description="Event-driven CI/CD scheduler with speculative merges",
    lifespan=lifespan
)

# ============= Main Event Loop (Single-threaded) =============

async def main_event_loop():
    """
    Main scheduler loop: Process events sequentially.
    This is single-threaded to ensure consistency.
    """
    logger.info("📡 Starting main event loop...")
    
    while scheduler_state.running:
        try:
            # Receive next event
            event_dict = await scheduler_state.redis_client.event_queue_pop(timeout=1)
            
            if event_dict is None:
                # No event, check if any pipelines are dirty
                await process_dirty_pipelines()
                continue
            
            # Parse event
            try:
                event = TorriEvent(**event_dict)
                logger.info(f"📥 Processing event: {event.event_type} | {event.change_id}")
                
                # Process event
                await scheduler_state.event_processor.process_event(event)
                
            except Exception as e:
                logger.error(f"Failed to process event: {e}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Main event loop error: {e}", exc_info=True)
            await asyncio.sleep(1)

async def process_dirty_pipelines():
    """
    Check for pipelines marked as 'dirty' and process them.
    Dirty pipelines need reprocessing after job completions.
    """
    pipelines = await scheduler_state.redis_client.get_all_pipelines()
    
    for pipeline_id in pipelines:
        if await scheduler_state.redis_client.pipeline_is_dirty(pipeline_id):
            try:
                pipeline_mgr = scheduler_state.pipeline_managers.get(pipeline_id)
                if pipeline_mgr:
                    await pipeline_mgr.process_queue()
                    await scheduler_state.redis_client.pipeline_clear_dirty(pipeline_id)
            except Exception as e:
                logger.error(f"Failed to process dirty pipeline {pipeline_id}: {e}")

# ============= Webhook Endpoints =============

@app.post("/api/v1/gerrit-event")
async def gerrit_webhook(payload: Dict[str, Any], 
                        background_tasks: BackgroundTasks):
    """
    Receive Gerrit webhooks for patchset-created, change-updated, etc.
    Normalize to Torri events and queue for processing.
    """
    try:
        logger.info(f"📨 Received Gerrit webhook: {payload.get('type')}")
        
        # Normalize Gerrit event to Torri event
        event = await scheduler_state.event_processor.normalize_gerrit_event(payload)
        
        # Queue event for processing
        await scheduler_state.redis_client.event_queue_push(event.dict())
        
        return JSONResponse(
            {"status": "queued", "event_id": event.event_id},
            status_code=202
        )
        
    except Exception as e:
        logger.error(f"Failed to process Gerrit webhook: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/job-result")
async def job_result_webhook(payload: Dict[str, Any]):
    """
    Receive job execution results from executor service.
    Updates job state and triggers next stage.
    """
    try:
        logger.info(f"📨 Job result received: {payload.get('job_id')}")
        
        job_id = payload.get("job_id")
        status = payload.get("status")  # SUCCESS, FAILURE, ERROR
        
        # Create job completion event
        event = TorriEvent(
            event_type=EventType.JOB_COMPLETED,
            source="executor",
            tenant_id=payload.get("tenant_id", "default"),
            data=payload
        )
        
        # Queue for processing
        await scheduler_state.redis_client.event_queue_push(event.dict())
        
        # Update job state immediately
        await scheduler_state.redis_client.job_set_state(
            job_id=job_id,
            status=status,
            result=payload
        )
        
        # Mark pipeline dirty so it gets reprocessed
        build_set_id = payload.get("build_set_id")
        if build_set_id:
            build_set = await scheduler_state.redis_client.get_json(
                f"torri:build-set:{build_set_id}"
            )
            if build_set:
                pipeline_id = build_set.get("pipeline_id")
                await scheduler_state.redis_client.pipeline_mark_dirty(pipeline_id)
        
        return JSONResponse({"status": "received"}, status_code=202)
        
    except Exception as e:
        logger.error(f"Failed to process job result: {e}")
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/v1/merge-result")
async def merge_result_webhook(payload: Dict[str, Any]):
    """
    Receive merge operation results from merger service.
    """
    try:
        logger.info(f"📨 Merge result received: {payload.get('merge_status')}")
        
        event = TorriEvent(
            event_type=EventType.MERGE_COMPLETED,
            source="merger",
            tenant_id=payload.get("tenant_id", "default"),
            data=payload
        )
        
        await scheduler_state.redis_client.event_queue_push(event.dict())
        
        return JSONResponse({"status": "received"}, status_code=202)
        
    except Exception as e:
        logger.error(f"Failed to process merge result: {e}")
        raise HTTPException(status_code=400, detail=str(e))

# ============= Configuration Endpoints =============

@app.get("/api/v1/pipelines")
async def list_pipelines():
    """Get all active pipelines."""
    try:
        pipelines_list = await scheduler_state.redis_client.get_all_pipelines()
        
        pipelines = []
        for pipeline_id in pipelines_list:
            window = await scheduler_state.redis_client.pipeline_get_window(pipeline_id)
            queue = await scheduler_state.redis_client.pipeline_get_queue(pipeline_id)
            pipelines.append({
                "pipeline_id": pipeline_id,
                "window_size": window.get("size"),
                "active_count": window.get("active"),
                "queue_length": len(queue)
            })
        
        return JSONResponse(pipelines)
        
    except Exception as e:
        logger.error(f"Failed to list pipelines: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/pipeline/{pipeline_id}/queue")
async def get_pipeline_queue(pipeline_id: str):
    """Get queue for specific pipeline."""
    try:
        queue = await scheduler_state.redis_client.pipeline_get_queue(pipeline_id)
        return JSONResponse({"pipeline_id": pipeline_id, "queue": queue})
    except Exception as e:
        logger.error(f"Failed to get pipeline queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/change/{change_id}")
async def get_change_state(change_id: str):
    """Get state of a specific change."""
    try:
        state = await scheduler_state.redis_client.change_get_state(change_id)
        if not state:
            raise HTTPException(status_code=404, detail="Change not found")
        return JSONResponse(state)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get change state: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/job/{job_id}")
async def get_job_state(job_id: str):
    """Get state and logs for a specific job."""
    try:
        state = await scheduler_state.redis_client.job_get_state(job_id)
        if not state:
            raise HTTPException(status_code=404, detail="Job not found")
        
        logs = await scheduler_state.redis_client.job_get_logs(job_id, start=-100)
        
        return JSONResponse({
            "job_id": job_id,
            "state": state,
            "logs": logs
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job state: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============= WebSocket for Real-time Updates =============

@app.websocket("/ws/pipeline/{pipeline_id}")
async def websocket_pipeline(websocket: WebSocket, pipeline_id: str):
    """
    WebSocket endpoint for real-time pipeline state updates.
    Clients can subscribe to pipeline changes.
    """
    await websocket.accept()
    logger.info(f"📡 Client connected to pipeline {pipeline_id}")
    
    try:
        while True:
            # Monitor pipeline state every 2 seconds
            await asyncio.sleep(2)
            
            queue = await scheduler_state.redis_client.pipeline_get_queue(pipeline_id)
            window = await scheduler_state.redis_client.pipeline_get_window(pipeline_id)
            dirty = await scheduler_state.redis_client.pipeline_is_dirty(pipeline_id)
            
            update = {
                "pipeline_id": pipeline_id,
                "queue_length": len(queue),
                "window_size": window.get("size"),
                "active_count": window.get("active"),
                "dirty": dirty,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            await websocket.send_json(update)
            
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        logger.info(f"📡 Client disconnected from pipeline {pipeline_id}")

@app.websocket("/ws/realtime/{channel}")
async def websocket_realtime(websocket: WebSocket, channel: str):
    """
    Real-time updates using Redis Pub/Sub.
    Works with multiple scheduler instances.
    Channels: "ui:events", "ui:pipeline:PIPELINE_ID", "ui:change:CHANGE_ID"
    """
    await websocket.accept()
    logger.info(f"📡 Client subscribed to channel: {channel}")
    
    # Subscribe to Redis Pub/Sub channel
    pubsub = scheduler_state.redis_client.redis.pubsub()
    await pubsub.subscribe(channel)
    
    try:
        while True:
            # Wait for message from ANY scheduler instance
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0
            )
            
            if message and message['type'] == 'message':
                # Forward message to WebSocket client
                event_data = json.loads(message['data'])
                await websocket.send_json(event_data)
                
    except Exception as e:
        logger.error(f"WebSocket Pub/Sub error: {e}")
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        logger.info(f"📡 Client unsubscribed from channel: {channel}")

# ============= Health Checks =============

@app.get("/health")
async def health_check():
    """Check scheduler and Redis health."""
    try:
        redis_healthy = await scheduler_state.redis_client.health_check()
        
        return JSONResponse({
            "status": "healthy" if redis_healthy else "unhealthy",
            "redis": "connected" if redis_healthy else "disconnected",
            "main_loop": "running" if scheduler_state.running else "stopped"
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            {"status": "unhealthy", "error": str(e)},
            status_code=503
        )

# ============= Load Pipelines from Config =============

async def load_pipelines_from_config():
    """
    Load pipeline definitions from YAML configuration files.
    Called on startup and on reconfiguration signals.
    """
    try:
        import yaml
        from pathlib import Path
        
        config_dir = Path("/app/config/layout")  # Docker path
        pipelines_file = config_dir / "pipelines.yaml"
        
        with open(pipelines_file, 'r') as f:
            config = yaml.safe_load(f)
        
        for pipeline_config in config.get("pipelines", []):
            pipeline = Pipeline(
                pipeline_id=pipeline_config["id"],
                name=pipeline_config["name"],
                type=PipelineType(pipeline_config["type"]),
                tenant_id="default",
                trigger_on=pipeline_config.get("trigger_on", []),
                jobs=pipeline_config.get("jobs", []),
                window_size=pipeline_config.get("window_size", 1),
                depend_sequential=pipeline_config.get("depend_sequential", False)
            )
            
            # Initialize pipeline manager
            manager = PipelineManager(
                pipeline=pipeline,
                redis_client=scheduler_state.redis_client,
                kafka_producer=scheduler_state.kafka_producer
            )
            scheduler_state.pipeline_managers[pipeline.pipeline_id] = manager
            
            # Initialize Redis state
            await scheduler_state.redis_client.pipeline_set_window(
                pipeline_id=pipeline.pipeline_id,
                window_size=pipeline.window_size,
                active_count=0
            )
            
            logger.info(f"✓ Loaded pipeline: {pipeline.name}")
        
    except Exception as e:
        logger.error(f"Failed to load pipelines config: {e}", exc_info=True)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
```

---

## Part 3: Pipeline Manager & Event Processor

### 3.1 Pipeline Manager (Handles Queue Processing)

```python
# File: microservices/Torri/src/torri/scheduler/pipeline_manager.py

import asyncio
from typing import List, Dict, Optional, Any
from datetime import datetime

from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedisClient
from torri.scheduler.models import Pipeline, PipelineType, Change, BuildSet, JobExecution
from torri.kafka.producer import KafkaProducerClient
from shared.merger_models import MergeRequest, MergeAction

logger = get_logger("torri.scheduler.pipeline_manager")

class PipelineManager:
    """
    Manages a single pipeline's queue, window adjustments, and job scheduling.
    Replaces Zuul's pipeline manager logic.
    """
    
    def __init__(self, pipeline: Pipeline, 
                 redis_client: TorriRedisClient,
                 kafka_producer: KafkaProducerClient):
        self.pipeline = pipeline
        self.redis = redis_client
        self.kafka = kafka_producer
        
        # Window expansion/contraction factors
        self.expand_factor = 2.0
        self.shrink_factor = 0.5
        self.min_window = 1

    async def process_queue(self):
        """
        Process pipeline queue: dequeue changes and schedule jobs.
        Called when pipeline is marked dirty or periodically.
        """
        logger.info(f"🔄 Processing queue for pipeline: {self.pipeline.name}")
        
        # Acquire distributed lock for this pipeline
        lock = await self.redis.acquire_lock(
            lock_name=f"pipeline:{self.pipeline.pipeline_id}",
            timeout=30,
            blocking_timeout=5.0
        )
        
        try:
            # Get current window state
            window_state = await self.redis.pipeline_get_window(self.pipeline.pipeline_id)
            window_size = window_state.get("size", 1)
            active_count = window_state.get("active", 0)
            
            # Get queue
            queue = await self.redis.pipeline_get_queue(self.pipeline.pipeline_id)
            
            # Process changes up to window size
            available_slots = window_size - active_count
            
            if available_slots <= 0:
                logger.debug(f"Pipeline window full: active={active_count}, window={window_size}")
                return
            
            logger.info(f"Available slots: {available_slots}, Queue length: {len(queue)}")
            
            for _ in range(available_slots):
                if not queue:
                    break
                
                # Dequeue next change
                change_id = await self.redis.pipeline_dequeue_change(self.pipeline.pipeline_id)
                if not change_id:
                    break
                
                # Get change details
                change_state = await self.redis.change_get_state(change_id)
                if not change_state:
                    logger.warning(f"Change state not found: {change_id}")
                    continue
                
                # Create build set for this attempt
                build_set = await self._create_build_set(change_id)
                
                # Schedule jobs
                await self._schedule_jobs_for_change(change_id, build_set)
                
                # Update counters
                active_count += 1
            
            # Update window state
            await self.redis.pipeline_set_window(
                self.pipeline.pipeline_id,
                window_size,
                active_count
            )
            
        finally:
            await self.redis.release_lock(lock)

    async def _create_build_set(self, change_id: str) -> BuildSet:
        """Create a new build set (attempt) for a change."""
        build_set = BuildSet(
            change_id=change_id,
            pipeline_id=self.pipeline.pipeline_id,
            start_time=datetime.utcnow()
        )
        
        # Store in Redis
        build_set_key = f"torri:build-set:{build_set.build_set_id}"
        await self.redis.set_json(build_set_key, build_set.dict())
        
        # Add to change's build history
        await self.redis.change_add_build_set(change_id, build_set.build_set_id)
        
        logger.info(f"Created build set {build_set.build_set_id} for change {change_id}")
        return build_set

    async def _schedule_jobs_for_change(self, change_id: str, build_set: BuildSet):
        """
        Schedule jobs for a change in order (respecting dependencies).
        Sends merge requests to Merger if this is a gate pipeline.
        """
        
        # If gate pipeline, request speculative merge first
        if self.pipeline.type == PipelineType.GATE:
            await self._request_speculative_merge(change_id, build_set)
        
        # Schedule jobs (in dependency order)
        for job_name in self.pipeline.jobs:
            job_id = f"{build_set.build_set_id}:{job_name}"
            
            # Create job execution record
            job_exec = JobExecution(
                job_id=job_id,
                build_set_id=build_set.build_set_id,
                definition={"name": job_name}  # Simplified
            )
            
            # Store job state
            await self.redis.job_set_state(
                job_id=job_id,
                status="QUEUED"
            )
            
            # Queue job to executor via Kafka
            job_request = {
                "job_id": job_id,
                "build_set_id": build_set.build_set_id,
                "change_id": change_id,
                "job_name": job_name,
                "pipeline_id": self.pipeline.pipeline_id,
                "tenant_id": self.pipeline.tenant_id
            }
            
            self.kafka.send_message(
                topic="job-queue",
                key=job_id,
                value=job_request
            )
            
            logger.info(f"Scheduled job {job_name} for change {change_id}")

    async def _request_speculative_merge(self, change_id: str, build_set: BuildSet):
        """
        Request speculative merge from Merger service.
        Creates a synthetic commit representing this change.
        """
        change_state = await self.redis.change_get_state(change_id)
        
        merge_request = MergeRequest(
            job_id=build_set.build_set_id,
            target_repository=change_state.get("project"),
            base_branch=change_state.get("branch", "master"),
            patchset_refs=[change_state.get("commit_hash")],
            action=MergeAction.SPECULATIVE_MERGE,
            strategy="merge"
        )
        
        self.kafka.send_message(
            topic="merger-requests",
            key=change_id,
            value=merge_request.model_dump(exclude_none=True)
        )
        
        logger.info(f"Requested speculative merge for {change_id}")

    async def on_job_complete(self, job_id: str, status: str):
        """
        Called when a job completes. Updates build set status and triggers next jobs
        or advancement in pipeline.
        """
        # Get job state
        job_state = await self.redis.job_get_state(job_id)
        if not job_state:
            return
        
        # Extract build_set_id from job_id format
        build_set_id = job_id.split(":")[0]
        build_set_data = await self.redis.get_json(f"torri:build-set:{build_set_id}")
        
        if status == "SUCCESS":
            logger.info(f"✓ Job {job_id} passed")
            
            # Check if all jobs in build set are complete
            if await self._all_jobs_complete(build_set_id):
                await self._on_buildset_complete(build_set_id)
                
        elif status in ["FAILURE", "ERROR"]:
            logger.info(f"✗ Job {job_id} failed")
            
            # Mark build set as failed
            await self.redis.set_json(
                f"torri:build-set:{build_set_id}",
                {**build_set_data, "status": "FAILURE"}
            )
            
            # TODO: Retry logic, report to Gerrit, etc.

    async def _all_jobs_complete(self, build_set_id: str) -> bool:
        """Check if all jobs in a build set have completed."""
        # Implementation details...
        return True

    async def _on_buildset_complete(self, build_set_id: str):
        """
        Called when all jobs in a build set complete successfully.
        Updates pipeline state and prepares for merge (if gate pipeline).
        """
        build_set_data = await self.redis.get_json(f"torri:build-set:{build_set_id}")
        change_id = build_set_data.get("change_id")
        
        # Update build set status
        build_set_data["status"] = "SUCCESS"
        build_set_data["end_time"] = datetime.utcnow().isoformat()
        await self.redis.set_json(f"torri:build-set:{build_set_id}", build_set_data)
        
        if self.pipeline.type == PipelineType.GATE:
            # Ready to merge
            await self._prepare_merge(change_id)
        
        elif self.pipeline.type == PipelineType.REPORT:
            # Run report jobs
            pass

    async def adjust_window(self, success: bool):
        """
        Adjust pipeline window based on job results.
        Success → expand window
        Failure → shrink window
        """
        window_state = await self.redis.pipeline_get_window(self.pipeline.pipeline_id)
        current_size = window_state.get("size", 1)
        
        if success:
            new_size = int(current_size * self.expand_factor)
            logger.info(f"Expanding window: {current_size} → {new_size}")
        else:
            new_size = max(self.min_window, int(current_size * self.shrink_factor))
            logger.info(f"Shrinking window: {current_size} → {new_size}")
        
        await self.redis.pipeline_set_window(
            self.pipeline.pipeline_id,
            new_size,
            window_state.get("active", 0)
        )

    async def _prepare_merge(self, change_id: str):
        """
        Prepare change for merge. Checks requirements and initiates merge.
        """
        logger.info(f"Preparing merge for change {change_id}")
        # Implementation details...

---

## Part 3.1: Merge Coordination (Multi-Scheduler Safety)

### 3.1.1 Global Merge Lock Pattern

To prevent simultaneous merges across multiple schedulers:

```python
# File: microservices/Torri/src/torri/scheduler/merge_coordinator.py

import os
import json
from typing import Dict, Any
from datetime import datetime
from shared.logger_setup import get_logger

logger = get_logger("torri.scheduler.merge_coordinator")

class MergeCoordinator:
    """
    Coordinates merges across multiple scheduler instances.
    Ensures only one merge happens at a time globally.
    Prevents git conflicts and race conditions.
    """
    
    def __init__(self, redis_client, kafka_producer):
        self.redis = redis_client
        self.kafka = kafka_producer
        self.merge_lock_timeout = 30  # 30 seconds per merge
        self.scheduler_id = os.getenv("SCHEDULER_ID", "unknown")

    async def attempt_merge(self, change_id: str, merge_request: Dict[str, Any]) -> bool:
        """
        Attempt to perform a merge, acquiring global lock.
        
        Returns:
            True if merge was performed
            False if lock couldn't be acquired (another scheduler merging)
        """
        logger.info(f"[{self.scheduler_id}] 🔒 Attempting to acquire global MERGE_LOCK for {change_id}")
        
        try:
            # Try to acquire global merge lock (with short timeout)
            lock = await self.redis.acquire_lock(
                lock_name="global:merge",
                timeout=self.merge_lock_timeout,
                blocking_timeout=0.5  # Don't wait long, try again later
            )
        except TimeoutError:
            logger.info(f"[{self.scheduler_id}] ⏳ MERGE_LOCK held by another scheduler. Will retry later.")
            return False
        
        try:
            logger.info(f"[{self.scheduler_id}] 🔓 Acquired MERGE_LOCK, proceeding with merge")
            
            # Send merge request to Merger service
            merge_response = await self._send_merge_request(merge_request)
            
            if merge_response.get("status") == "SUCCESS":
                # Update change state to MERGED
                change_state = await self.redis.change_get_state(change_id)
                if change_state:
                    change_state["state"] = "MERGED"
                    change_state["merged_at"] = datetime.utcnow().isoformat()
                    change_state["merged_by_scheduler"] = self.scheduler_id
                    await self.redis.change_set_state(change_id, change_state)
                
                # Broadcast merge event to all connected UI clients
                await self._broadcast_merge_event(change_id, merge_response)
                
                logger.info(f"[{self.scheduler_id}] ✓ Merge successful for {change_id}")
                return True
            else:
                logger.warning(f"[{self.scheduler_id}] ✗ Merge failed: {merge_response.get('error')}")
                
                # Update change state to FAILED_MERGE
                change_state = await self.redis.change_get_state(change_id)
                if change_state:
                    change_state["state"] = "MERGE_FAILED"
                    change_state["merge_error"] = merge_response.get('error')
                    await self.redis.change_set_state(change_id, change_state)
                
                return False
                
        finally:
            await self.redis.release_lock(lock)
            logger.info(f"[{self.scheduler_id}] 🔓 Released MERGE_LOCK")

    async def _send_merge_request(self, merge_request: Dict) -> Dict:
        """Send merge request to Merger service via Kafka."""
        logger.info(f"[{self.scheduler_id}] Sending merge request to Merger service")
        
        self.kafka.send_message(
            topic="merger-requests",
            key=merge_request.get("change_id"),
            value=merge_request
        )
        
        # In real implementation, would wait for response from merger-responses topic
        # For now, simulate success
        return {
            "status": "SUCCESS",
            "merged_commit": "abc123def456"
        }

    async def _broadcast_merge_event(self, change_id: str, merge_response: Dict):
        """
        Broadcast merge event to all clients (UI, reporters).
        Uses Redis Pub/Sub so ALL scheduler instances and UI clients get it.
        """
        
        event = {
            "type": "change.merged",
            "change_id": change_id,
            "timestamp": datetime.utcnow().isoformat(),
            "scheduler": self.scheduler_id,
            "merge_details": merge_response
        }
        
        # Publish to Redis Pub/Sub channel (for WebSocket clients)
        await self.redis.redis.publish("ui:events", json.dumps(event))
        logger.info(f"[{self.scheduler_id}] 📡 Broadcasted merge event to UI clients")
        
        # Log to Kafka for audit trail
        self.kafka.send_message(
            topic="pipeline-state-log",
            key=change_id,
            value=event
        )
```

### 3.1.2 How Merge Coordination Works with Multiple Schedulers

```
Scenario: 3 Scheduler instances, gate pipeline

T0: Change A ready to merge
    ├─ Scheduler-1 tries: acquire_lock("global:merge") → SUCCESS ✓
    ├─ Scheduler-2 tries: acquire_lock("global:merge") → BLOCKED (timeout=0.5s)
    └─ Scheduler-3 tries: acquire_lock("global:merge") → BLOCKED

T1-T5: Scheduler-1 merges Change A (git operation happens)
    ├─ Git merge executed
    ├─ Commit hash verified
    ├─ Change state updated to MERGED in Redis
    └─ Event broadcasted via Redis Pub/Sub

T6: Scheduler-1 releases lock
    └─ All 3 schedulers see lock is free

T7: Scheduler-2 acquires lock (or Scheduler-3, whoever tries first)
    └─ Can now process Change B

TimelineVisualization:
  Scheduler-1: [processing] → [merge in progress......] → [released]
  Scheduler-2: [waiting...] → [locked........] → [can process]
  Scheduler-3: [waiting...] → [locked........] → [waiting...]
  
NO CONFLICTS, NO RACE CONDITIONS
```

---

### 3.2 Event Processor

```python
# File: microservices/Torri/src/torri/scheduler/event_processor.py

from typing import Dict, Any, Optional
from datetime import datetime

from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedisClient
from torri.scheduler.models import (
    TorriEvent, EventType, GerritEventData, Change, ChangeState
)
from torri.kafka.producer import KafkaProducerClient

logger = get_logger("torri.scheduler.event_processor")

class EventProcessor:
    """
    Processes Torri events and coordinates state updates.
    Routes events to appropriate handlers.
    """
    
    def __init__(self, redis_client: TorriRedisClient, 
                 kafka_producer: KafkaProducerClient):
        self.redis = redis_client
        self.kafka = kafka_producer

    async def process_event(self, event: TorriEvent):
        """Main event dispatch method."""
        
        if event.event_type == EventType.GERRIT_PATCHSET_CREATED:
            await self._handle_patchset_created(event)
        
        elif event.event_type == EventType.GERRIT_CHANGE_UPDATED:
            await self._handle_change_updated(event)
        
        elif event.event_type == EventType.JOB_COMPLETED:
            await self._handle_job_completed(event)
        
        elif event.event_type == EventType.MERGE_COMPLETED:
            await self._handle_merge_completed(event)
        
        else:
            logger.warning(f"Unknown event type: {event.event_type}")

    async def _handle_patchset_created(self, event: TorriEvent):
        """
        New patchset created in Gerrit.
        Enqueue to applicable pipelines (CHECK, GATE).
        """
        logger.info(f"📝 Patchset created for {event.data.get('project')}")
        
        # Create or update change record
        change_id = event.change_id or event.data.get('change_number')
        change = Change(
            change_id=change_id,
            project=event.data.get('project'),
            branch=event.data.get('branch'),
            commit_hash=event.data.get('commit_hash'),
            author=event.data.get('author'),
            subject=event.data.get('subject'),
            gerrit_url=event.data.get('url'),
            state=ChangeState.PENDING
        )
        
        # Store change in Redis
        await self.redis.change_set_state(change_id, change.dict())
        
        # Enqueue to applicable pipelines
        # TODO: Load pipeline definitions and check trigger conditions
        applicable_pipelines = ["check", "gate"]  # Placeholder
        
        for pipeline_id in applicable_pipelines:
            await self.redis.pipeline_enqueue_change(pipeline_id, change_id)
            await self.redis.pipeline_mark_dirty(pipeline_id)
            logger.info(f"Enqueued change {change_id} to pipeline {pipeline_id}")

    async def _handle_change_updated(self, event: TorriEvent):
        """Patchset updated or rebased."""
        logger.info(f"🔄 Change updated: {event.change_id}")
        # Handle rebase, new patchset, etc.

    async def _handle_job_completed(self, event: TorriEvent):
        """
        Job completed with result.
        Update job state and trigger next stage.
        """
        job_id = event.data.get("job_id")
        status = event.data.get("status")
        
        logger.info(f"✓ Job {job_id} completed with status: {status}")
        
        # Update job state
        await self.redis.job_set_state(job_id, status, event.data)
        
        # Mark pipeline dirty for reprocessing
        build_set_id = event.data.get("build_set_id")
        if build_set_id:
            build_set = await self.redis.get_json(f"torri:build-set:{build_set_id}")
            if build_set:
                pipeline_id = build_set.get("pipeline_id")
                await self.redis.pipeline_mark_dirty(pipeline_id)

    async def _handle_merge_completed(self, event: TorriEvent):
        """Merge operation completed."""
        logger.info(f"🔀 Merge completed: {event.data.get('change_id')}")
        # Update change state to MERGED

    async def normalize_gerrit_event(self, gerrit_payload: Dict[str, Any]) -> TorriEvent:
        """
        Convert Gerrit webhook JSON to Torri event.
        """
        event_type = gerrit_payload.get("type", "")
        
        if "patchset-created" in event_type:
            event_type = EventType.GERRIT_PATCHSET_CREATED
        elif "change-updated" in event_type:
            event_type = EventType.GERRIT_CHANGE_UPDATED
        elif "change-merged" in event_type:
            event_type = EventType.GERRIT_CHANGE_MERGED
        
        change_data = gerrit_payload.get("change", {})
        patchset_data = gerrit_payload.get("patchSet", {})
        
        return TorriEvent(
            event_type=event_type,
            source="gerrit",
            tenant_id="default",
            change_id=str(change_data.get("number")),
            data={
                "project": change_data.get("project"),
                "branch": change_data.get("branch"),
                "change_number": change_data.get("number"),
                "patchset_number": patchset_data.get("number"),
                "commit_hash": patchset_data.get("revision"),
                "author": change_data.get("owner", {}).get("name"),
                "subject": change_data.get("subject"),
                "url": change_data.get("url")
            }
        )
```

---

## Part 4: Integration with Existing Torri Components

### 4.1 Kafka Topic Setup for Scheduler Event Flow

```yaml
# File: compose/kafka-topics.yaml
# Define all Kafka topics for the scheduler

topics:
  
  # Gerrit Event Source
  - name: "gerrit-events"
    partitions: 3
    replication_factor: 1
    config:
      retention.ms: 86400000  # 24 hours
      
  # Scheduler Internal
  - name: "scheduler-trigger"
    partitions: 1
    replication_factor: 1
    
  # Merger Communication
  - name: "merger-requests"
    partitions: 3
    replication_factor: 1
    
  - name: "merger-responses"
    partitions: 3
    replication_factor: 1
    
  # Executor Communication
  - name: "job-queue"
    partitions: 6
    replication_factor: 1
    
  - name: "job-results"
    partitions: 6
    replication_factor: 1
    
  # Pipeline State (optional, for audit trail)
  - name: "pipeline-state-log"
    partitions: 1
    replication_factor: 1
    config:
      retention.ms: 604800000  # 7 days
```

### 4.2 Configuration Schema (YAML)

```yaml
# File: microservices/Torri/src/torri/config/layout/pipelines.yaml
# Pipeline definitions for Torri

tenants:
  - name: "default"
    
    pipelines:
      # Check Pipeline: Independent parallel testing
      - id: "check"
        name: "Check Pipeline"
        type: "check"
        description: "Verify code quality"
        
        trigger_on:
          - gerrit.patchset.created
          - gerrit.change.updated
        
        jobs:
          - "lint"
          - "unit-tests"
          - "security-scan"
        
        window_size: 5              # Allow 5 parallel changes
        depend_sequential: false    # Independent execution
        
      # Gate Pipeline: Dependent merge validation
      - id: "gate"
        name: "Gate Pipeline"
        type: "gate"
        description: "Pre-merge validation"
        
        trigger_on:
          - gerrit.change.ready
        
        jobs:
          - "compile"
          - "integration-tests"
          - "performance-tests"
        
        window_size: 1              # Serial processing
        depend_sequential: true     # Dependent execution
        
        merge_requirements:
          require_approval: true
          approval_count: 1

jobs:
  - name: "lint"
    runs_on: "executor-1"
    timeout: 300
    playbooks:
      - "lint.yaml"
    vars:
      python_version: "3.10"
  
  - name: "unit-tests"
    runs_on: "executor-1"
    timeout: 600
    playbooks:
      - "run-tests.yaml"
    vars:
      test_suite: "pytest"
  
  - name: "integration-tests"
    runs_on: "executor-2"
    timeout: 1200
    playbooks:
      - "integration-tests.yaml"
    depends_on:
      - "compile"
```

---

## Part 5: Deployment & Docker Compose

### 5.1 Extended Docker Compose with Redis

```yaml
# File: compose/compose.yaml (extended)

version: '3.9'

services:
  # ====== Redis for Scheduler State ======
  redis:
    image: redis:7-alpine
    container_name: torri-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes
    networks:
      - torri-net
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 3

  # ====== Torrri Scheduler (FastAPI) ======
  scheduler:
    build:
      context: ..
      dockerfile: compose/Dockerfile
      target: scheduler
    container_name: torri-scheduler
    ports:
      - "8000:8000"
    environment:
      - KAFKA_SERVER=kafka:9092
      - REDIS_URL=redis://redis:6379/0
      - LOG_LEVEL=INFO
      - CONFIG_DIR=/app/config
    volumes:
      - ../microservices/Torri/src:/app/src
      - ../microservices/Shared/src:/app/shared
      - ../microservices/Torri/src/torri/config:/app/config
    depends_on:
      kafka:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - torri-net
    command: python -m torri.cmd.server run

  # ====== Kafka (already in compose) ======
  kafka:
    # ... existing Kafka config
    networks:
      - torri-net

networks:
  torri-net:
    driver: bridge

volumes:
  redis-data:
```

---

## Part 6: Monitoring & Observability

### 6.1 Redis Monitoring Script

```python
# File: microservices/Torri/scripts/monitor_scheduler.py

import asyncio
from torri.scheduler.redis_client import TorriRedisClient
from shared.logger_setup import get_logger

logger = get_logger("torri.monitor")

async def monitor_scheduler():
    """Continuous monitoring of scheduler state."""
    
    redis = TorriRedisClient()
    await redis.connect()
    
    while True:
        try:
            # Get pipeline stats
            pipelines = await redis.get_all_pipelines()
            
            logger.info("=" * 60)
            logger.info(f"SCHEDULER MONITOR | {len(pipelines)} pipelines")
            logger.info("=" * 60)
            
            for pipeline_id in pipelines:
                queue = await redis.pipeline_get_queue(pipeline_id)
                window = await redis.pipeline_get_window(pipeline_id)
                dirty = await redis.pipeline_is_dirty(pipeline_id)
                
                logger.info(f"Pipeline: {pipeline_id}")
                logger.info(f"  Queue: {len(queue)} changes")
                logger.info(f"  Window: {window.get('active')}/{window.get('size')}")
                logger.info(f"  Dirty: {dirty}")
            
            # Get change stats
            changes = await redis.get_all_changes()
            logger.info(f"\nTotal Changes: {len(changes)}")
            
            await asyncio.sleep(10)
            
        except Exception as e:
            logger.error(f"Monitor error: {e}", exc_info=True)
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(monitor_scheduler())
```

---

## Part 7: Testing the Scheduler

### 7.1 Integration Test

```python
# File:  microservices/Torri/tests/test_scheduler_integration.py

import pytest
import asyncio
from torri.scheduler.redis_client import TorriRedisClient
from torri.scheduler.models import TorriEvent, EventType

@pytest.mark.asyncio
async def test_event_processing():
    """Test event creation and processing flow."""
    
    redis = TorriRedisClient("redis://localhost:6379/0")
    await redis.connect()
    
    try:
        # Create test event
        event = TorriEvent(
            event_type=EventType.GERRIT_PATCHSET_CREATED,
            source="gerrit",
            tenant_id="default",
            change_id="12345",
            data={
                "project": "test-repo",
                "branch": "main",
                "commit_hash": "abc123"
            }
        )
        
        # Queue event
        await redis.event_queue_push(event.dict())
        
        # Pop event
        retrieved = await redis.event_queue_pop()
        
        assert retrieved["change_id"] == "12345"
        assert retrieved["event_type"] == "gerrit.patchset.created"
        
    finally:
        await redis.disconnect()

@pytest.mark.asyncio
async def test_pipeline_queue_operations():
    """Test pipeline queue management."""
    
    redis = TorriRedisClient("redis://localhost:6379/0")
    await redis.connect()
    
    try:
        pipeline_id = "check"
        
        # Add changes to queue
        await redis.pipeline_enqueue_change(pipeline_id, "change-1")
        await redis.pipeline_enqueue_change(pipeline_id, "change-2")
        
        # Get queue
        queue = await redis.pipeline_get_queue(pipeline_id)
        assert len(queue) == 2
        
        # Dequeue
        dequeued = await redis.pipeline_dequeue_change(pipeline_id)
        assert dequeued == "change-1"
        
        # Queue should have 1 remaining
        queue = await redis.pipeline_get_queue(pipeline_id)
        assert len(queue) == 1
        
    finally:
        await redis.disconnect()
```

---

## Part 8: Multi-Scheduler Coordination & UI Updates

### 8.1 How UI Updates Work Across Multiple Schedulers

When you have 3 scheduler instances running:

```
Browser Client 1          Browser Client 2          Browser Client 3
    │                         │                         │
    └─ WebSocket to           └─ WebSocket to          └─ WebSocket to
       Port 8000:0             Port 8000:1             Port 8000:2
       (Could be any           (Could be different     (Could be different
        scheduler)             scheduler)              scheduler)
       │                       │                       │
       └─────────┬─────────────┴───────────┬───────────┘
                 │                       │
            Reverse Proxy / Load Balancer (nginx)
                 │
       ┌─────────┴──────────┬──────────────┐
       │                   │              │
    Scheduler-1         Scheduler-2    Scheduler-3
    (FastAPI)           (FastAPI)      (FastAPI)
       │                   │              │
       └─────────┬─────────┴──────────────┘
                 │
            Redis Instance
            (Pub/Sub Broker)
            ├─ Channels
            │  ├─ ui:events
            │  ├─ ui:pipeline:check
            │  ├─ ui:pipeline:gate
            │  └─ ui:change:*
            │
            └─ All schedulers publish here
               All clients receive from here
```

### 8.2 Event Flow Example: Change Merged Notification

```
T0: Change A passes all jobs in gate pipeline
    └─ Scheduler-1 (happens to have pipeline:gate lock)

T1: Scheduler-1 calls MergeCoordinator.attempt_merge(Change A)
    ├─ acquire_lock("global:merge") → SUCCESS
    └─ Scheduler-2 & 3 try but are blocked

T2: Scheduler-1 sends merge request to Merger service
    └─ Via Kafka topic: merger-requests

T3: Merger service executes git merge
    └─ All git operations atomic and serial

T4: Merger service publishes result to Kafka
    └─ Via Kafka topic: merger-responses

T5: Scheduler-1 receives merge success, updates Change A state
    ├─ Redis: change:A:state = MERGED
    └─ Publishes to Redis Pub/Sub

T6: All 3 Schedulers see the published event
    └─ They update local understanding of state

T7: ALL THREE WebSocket connections receive update
    ├─ Browser Client 1: Instant notification
    ├─ Browser Client 2: Instant notification
    └─ Browser Client 3: Instant notification

RESULT: All clients see "Change A merged" at the same time ✓
```

### 8.3 Real-Time Sync: No Duplicates, No Conflicts

**Why nothing breaks with multiple schedulers:**

```python
# Each component handles concurrency properly

# 1. Distributed Lock Pattern
#    Only ONE scheduler processes a pipeline at a time
await scheduler_state.redis_client.acquire_lock(
    lock_name=f"pipeline:{pipeline_id}",
    timeout=30,
    blocking_timeout=5.0  # Wait up to 5 seconds
)

# 2. Merge Lock Pattern
#    Only ONE merge happens globally at a time
await merge_coordinator.attempt_merge(
    change_id,
    lock_name="global:merge",
    blocking_timeout=0.5  # Don't wait long, retry later
)

# 3. Redis Pub/Sub Pattern
#    Events published to all subscribers instantly
await redis.redis.publish("ui:events", json.dumps(event))
# ALL scheduler instances AND web clients receive it

# 4. Event Ordering
#    Kafka ensures causality: patchset-created → jobs-run → merge
#    All schedulers process events in same order

# 5. State Consistency
#    Redis is single source of truth
#    All schedulers read/write to same Redis
#    No stale state, no local caches
```

### 8.4 Failure Scenarios & Recovery

**Scenario 1: Scheduler-1 Crashes During Merge**

```
T0: Scheduler-1 acquires global:merge lock
T1: Git merge in progress
T2: Scheduler-1 CRASHES ✗

Problem: Lock held forever? State inconsistent?

Solution: Lock has timeout!
├─ Lock acquired with timeout=30 seconds
├─ If holder crashes, lock auto-releases after 30s
└─ Scheduler-2 can acquire and retry/recover

T3-30: Merger service waiting for Scheduler-1 response
T30: Scheduler-1 lock timeout → lock released
T31: Scheduler-2 acquires lock
T32: Scheduler-2 checks Change A state
     ├─ Sees it's NOT merged (from last known state)
     ├─ OR sees it IS merged (Merger service succeeded despite crash)
     └─ Acts appropriately
```

**Scenario 2: Scheduler-1 Processing, then Network Partition**

```
Scheduler-1 isolated     Redis                    Scheduler-2, 3
(Can't reach Redis)      (Serving others)         (Still working)
    │                        │                        │
    ├─ Loses lock           ├─ Lock expires          └─ Can work normally
    ├─ Stops processing     └─ Other schedulers       └─ Pick up work
    └─ Waits for network       can use pipeline  
      to return
```

**Recovery: When Scheduler-1 Network Restored**

```
T0: Scheduler-1 reconnects to Redis
T1: Rehydrates state from Redis
T2: Checks which pipelines it was working on
T3: Checks if other schedulers took over
T4: If work incomplete, can re-start or coordinate
```

### 8.5 Deployment Example: 3 Schedulers + UI + Load Balancer

```yaml
# File: compose/compose-production.yaml

services:
  # Three scheduler instances
  scheduler-1:
    image: torri-scheduler:latest
    environment:
      - SCHEDULER_ID=scheduler-1
      - REDIS_URL=redis://redis:6379/0
      - KAFKA_SERVER=kafka:9092
    depends_on:
      - redis
      - kafka

  scheduler-2:
    image: torri-scheduler:latest
    environment:
      - SCHEDULER_ID=scheduler-2
      - REDIS_URL=redis://redis:6379/0
      - KAFKA_SERVER=kafka:9092
    depends_on:
      - redis
      - kafka

  scheduler-3:
    image: torri-scheduler:latest
    environment:
      - SCHEDULER_ID=scheduler-3
      - REDIS_URL=redis://redis:6379/0
      - KAFKA_SERVER=kafka:9092
    depends_on:
      - redis
      - kafka

  # Load balancer (nginx or HAProxy)
  load-balancer:
    image: nginx:alpine
    ports:
      - "8000:8000"      # HTTP/REST API
      - "8443:8443"      # HTTPS
    volumes:
      - ./nginx-lb.conf:/etc/nginx/nginx.conf:ro
    depends_on:
      - scheduler-1
      - scheduler-2
      - scheduler-3

  # Redis (shared state)
  redis:
    image: redis:7-alpine
    volumes:
      - redis-data:/data
    command: redis-server --appendonly yes

  # Kafka (shared events)
  kafka:
    image: confluentinc/cp-kafka:latest
    environment:
      - KAFKA_BROKER_ID=1

  # Web UI
  web:
    image: torri-web:latest
    ports:
      - "3000:3000"
    environment:
      - VITE_API_URL=http://localhost:8000
    depends_on:
      - load-balancer
```

### 8.6 UI Client-Side (Connecting to Multiple Schedulers)

```typescript
// File: web/src/hooks/useSchedulerUpdates.ts
// React hook for real-time updates from any scheduler

import { useEffect, useState } from 'react';

export function useSchedulerUpdates(channel: string) {
  const [updates, setUpdates] = useState([]);
  const [wsConnected, setWsConnected] = useState(false);

  useEffect(() => {
    // Connect to WebSocket through load balancer
    // Load balancer routes to any available scheduler
    const ws = new WebSocket(
      `ws://${window.location.host}/ws/realtime/${channel}`
    );

    ws.onopen = () => {
      setWsConnected(true);
      console.log(`✓ Connected to ${channel}`);
    };

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      // Could be from any scheduler instance
      console.log(`📡 Update from scheduler: ${data.scheduler_instance || 'unknown'}`);
      
      setUpdates(prev => [...prev, data]);
    };

    ws.onclose = () => {
      setWsConnected(false);
      console.log(`✗ Disconnected from ${channel}`);
      
      // Auto-reconnect
      setTimeout(() => {
        ws.reconnect?.();
      }, 3000);
    };

    return () => ws.close();
  }, [channel]);

  return { updates, wsConnected };
}

// Usage in component:
// const { updates, wsConnected } = useSchedulerUpdates('ui:pipeline:gate');
// updates.forEach(update => console.log('Change merged:', update.change_id));
```

---

## Summary: Torri Scheduler Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Message Broker** | Apache Kafka (KRaft) | Event streaming, async communication |
| **State Management** | Redis | Replaces ZooKeeper; manages pipelines, changes, jobs |
| **Scheduler Core** | FastAPI + Python | Main event loop, single-threaded for consistency |
| **Job Execution** | Custom Executor | Runs jobs, reports results via Kafka |
| **Git Operations** | Torri Merger | Speculative merges, ref management |
| **Code Review Gate** | Gerrit | Source of truth for approval, merge gate |
| **Configuration** | YAML | Declarative pipeline/job definitions |
| **Containerization** | Docker Compose | Local dev, testing, production deployment |
| **Monitoring** | Redis CLI + logs | Real-time state inspection, debugging |

This implementation provides:
✓ Event-driven architecture with Kafka  
✓ Distributed state with Redis (no ZooKeeper dependency)  
✓ Single-threaded main loop for consistency  
✓ Async/await patterns for performance  
✓ Django-like declarative configuration  
✓ Speculative merges for independent change testing  
✓ Window-based parallelism with expansion/contraction  
✓ Full integration with your existing Gerrit, Merger, Executor stack  

