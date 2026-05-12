# Torii Scheduler Flow & Architecture

## System Overview

The Torii scheduler is a threading-based event processing system that monitors Gerrit changes and routes them through configurable CI/CD pipelines (Check, Gate, Report). Changes flow through a series of components that enrich events, verify approvals, and manage queue-based pipeline execution.

## Components

### 1. Kafka Consumer (`KafkaConnection`)
- **Role**: Pulls raw Gerrit events from Kafka topic `gerrit-stream-events`
- **Type**: `threading.Thread` (daemon)
- **Output**: Puts raw JSON events into `event_queue`
- **Lifecycle**: Runs continuously, polling Kafka for new events

### 2. Event Enricher (`GerritEventProcessor`)
- **Role**: Enriches raw Kafka events with full change details from Gerrit API
- **Type**: `threading.Thread` (daemon)
- **Input**: Raw events from `KafkaConnection.event_queue`
- **Process**:
  1. Parse raw JSON from Kafka
  2. Extract change ID
  3. Call `GerritRestConnection.getChange(change_id)` to fetch full details
  4. Create `GerritTriggerEvent` object with enriched data
  5. Dispatch to scheduler via `gerrit_connection.sched.addEvent(event)`
- **Output**: Enriched `GerritTriggerEvent` objects sent to SchedulerQueue

### 3. Scheduler Queue (`SchedulerQueue`)
- **Role**: Main orchestrator that makes routing decisions and manages pipelines
- **Type**: `threading.Thread` (daemon)
- **Input**: Enriched events from `GerritEventProcessor` via `addEvent()` method
- **Process**: See "Change Processing Lifecycle" below
- **Internal Components**:
  - `event_queue`: Unbounded `queue.Queue` for buffering incoming events (timeout 5s per put)
  - `pipelines`: Dict mapping pipeline IDs to pipeline manager instances
  - `config`: `ConfigurationLoader` for YAML-based configuration
  - `approval_verifier`: Checks if change has required labels
  - `redis`: `TorriRedis` client for persistent state

### 4. Redis State Store (`TorriRedis`)
- **Role**: Persists change state, pipeline queues, locks, and build tracking
- **Type**: Simple synchronous Redis wrapper
- **Thread-Safe**: Yes (Redis operations are atomic)
- **Key Patterns**:
  ```
  torri:change:{change_id}:state           # Current state of a change
  torri:pipeline:{pipeline_id}:queue       # FIFO queue of change IDs
  torri:pipeline:{pipeline_id}:window      # Concurrency window state
  torri:buildset:{buildset_id}:state       # Job execution attempt tracking
  torri:job:{job_id}:logs                  # Job output/logs
  torri:lock:pipeline:{pipeline_id}        # Distributed lock for pipeline access
  torri:lock:global:merge                  # Global merge lock
  ```

### 5. Pipeline Managers (`CheckPipeline`, `GatePipeline`, `ReportPipeline`)
- **Role**: Manage queuing and concurrency for each pipeline type
- **State**: Stored in Redis, loaded into memory for fast access
- **Responsibilities**:
  - Enqueue changes (append to Redis queue)
  - Dequeue changes (pop from Redis queue)
  - Track window size (how many changes can run concurrently)
  - Track active count (how many are currently running)
  - Manage build sets (job execution attempts)

---

## Change Processing Lifecycle

### Phase 1: Event Reception (KafkaConnection → GerritEventProcessor)

```
1. Kafka topic: gerrit-stream-events receives new event
2. KafkaConnection thread polls Kafka
3. Raw JSON put into KafkaConnection.event_queue
4. GerritEventProcessor reads from event_queue
5. Event dispatched to GerritEventProcessor._on_event(raw_data)
```

**Example raw event:**
```json
{
  "type": "patchset-created-event",
  "change": {
    "number": 12345,
    "id": "project~branch~change_id",
    "project": "my-project",
    "branch": "main",
    "commitMessage": "Fix bug in parser"
  },
  "upstreamRef": "refs/heads/main"
}
```

### Phase 2: Event Enrichment (GerritEventProcessor)

```
1. Extract change number from raw event
2. Call gerrit_connection.getChange(change_number)
3. GerritRestConnection fetches full change details from Gerrit API
4. Response cached in LRU cache (10k changes max)
5. Create GerritTriggerEvent with enriched data
6. Call gerrit_connection.sched.addEvent(enriched_event)
```

**Result: GerritTriggerEvent object with full details**
```python
event.change.number           # 12345
event.change.project          # "my-project"
event.change.branch           # "main"
event.change.subject          # "Fix bug in parser"
event.change.labels           # {"Code-Review": +1, "Verified": 0}
event.change.owner            # {"name": "John", "email": "john@..."}
```

### Phase 3: Approval Verification (SchedulerQueue)

```
1. Event received in SchedulerQueue.addEvent()
2. Put into internal event_queue (async buffering)
3. SchedulerQueue.run() loop retrieves event with 1s timeout
4. Call approval_verifier.verify_project_approval(change_id, project_name)
5. Load project config: which approval labels are required?
6. Extract current labels from change object
7. Compare: if any required label < required value, DENY
8. If approved, proceed to pipeline routing
9. If not approved, post message to Gerrit and SKIP change
```

**Approval Check Example:**
```yaml
# projects.yaml
my-project:
  approval_labels:
    - name: "Code-Review"
      value: 1        # Requires +1 from reviewer
    - name: "Verified"
      value: 1        # Requires +1 from CI (gate pipeline)
```

**Decision Logic:**
- If Code-Review < +1: NOT APPROVED → Skip to Gerrit message
- If Code-Review >= +1 AND Verified < +1: APPROVED for Check pipeline only
- If both >= +1: APPROVED for all pipelines (including Gate)

### Phase 4: Pipeline Routing & Enqueuing (SchedulerQueue)

```
1. Get pipelines list from project config
2. For each pipeline (check, gate, report):
   a. Call approval_verifier.verify_pipeline_approval(change_id, pipeline_id)
   b. If approved:
      - Call pipeline.enqueue_change(change_id)
      - Pipeline appends to Redis queue: RPUSH torri:pipeline:{id}:queue change_id
      - Return queue position (1-based)
   c. If not approved: Log and skip
3. Create ChangeInfoModel with state=QUEUED
4. Save change_state to Redis
5. Log: "Change {id} queued to pipelines: [check, gate]"
```

**Example Result in Redis:**
```
LRANGE torri:pipeline:check:queue 0 -1
→ ["12345", "12344", "12343"]  # Position 1 for change 12345

SET torri:change:12345:state {
  "change_id": "12345",
  "project_name": "my-project",
  "branch": "main",
  "state": "queued",
  "buildsets": [],
  "queue_position": 1,
  "created_at": "2026-05-11T10:30:45.123456"
}
```

### Phase 5: Pipeline Processing (Future - Not Implemented Yet)

```
DEQUEUE LOOP (would run periodically):
1. For each pipeline:
   a. Check window: if active_count < window_size:
      - Can dequeue and start processing
   b. Call pipeline.dequeue_change()
      - LPOP torri:pipeline:{id}:queue
      - Get first change ID from queue
   c. Create BuildSet (job execution attempt)
   d. Dispatch jobs to executor
   e. Poll for job completion
   f. Update pipeline window (decrement active_count on completion)
   g. If Gate pipeline success + pipeline.should_merge():
      - Trigger merger to merge change into base branch
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ KAFKA: gerrit-stream-events                                      │
│ Events: patchset-created, change-updated, etc.                   │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
        ┌──────────────────────────────┐
        │ KafkaConnection (thread)      │
        │ - Poll kafka                  │
        │ - Parse JSON                  │
        │ - Put in event_queue          │
        └──────────┬───────────────────┘
                   │
                   ▼
        ┌──────────────────────────────────────┐
        │ GerritEventProcessor (thread)         │
        │ - Read from kafka queue               │
        │ - Fetch full change via REST API      │
        │ - Call scheduler.sched.addEvent()     │
        └──────────┬──────────────────────────┘
                   │
                   ▼
        ┌────────────────────────────────────────┐
        │ SchedulerQueue (thread)                 │
        │ - Receive enriched event               │
        │ - Check project approvals              │
        │ - Route to pipelines                   │
        │ - Enqueue to Redis                     │
        └────────┬──────────────────────────────┘
                 │
        ┌────────┴────────┬────────────┬──────────┐
        │                 │            │          │
        ▼                 ▼            ▼          ▼
   ┌────────┐       ┌────────┐   ┌────────┐ ┌────────┐
   │ Redis  │───────│ Pipeline│───│ Pipeline│ │Pipeline│
   │ Queues │       │ Check   │   │ Gate    │ │ Report │
   │        │       │         │   │         │ │        │
   │ • check│       │ W:5     │   │ W:1     │ │ W:10   │
   │ • gate │────────         │   │         │ │        │
   │ • report       │ Changes │   │ Changes │ │Changes │
   └────────┘       │ 12345   │   │ 12346   │ │ 12344  │
                    │ 12344   │   │ 12345   │ │ 12343  │
                    └────────┘   └────────┘ └────────┘
```

---

## Configuration

### projects.yaml
```yaml
my-project:
  merge_strategy: merge              # merge | rebase | squash | cherry-pick
  approval_labels:
    - name: "Code-Review"
      value: 1                        # Min +1 required
      blocking: false
  pipelines:
    - check                           # Route to check pipeline
    - gate                            # Route to gate pipeline

another-project:
  merge_strategy: squash
  approval_labels:
    - name: "Code-Review"
      value: 2                        # Min +2 (more strict)
  pipelines:
    - check
    - gate
    - report
```

### pipelines.yaml
```yaml
check:
  name: "Verification Pipeline"
  type: check                         # Can't trigger merge
  window_size: 5                      # Up to 5 changes in parallel
  jobs:
    - lint
    - unit-tests
    - code-coverage
  trigger_events:
    - patchset-created
    - change-updated
  approval_labels: []                 # No extra approval requirements

gate:
  name: "Merge Gating Pipeline"
  type: gate                          # Can trigger merge
  window_size: 1                      # Serial processing (one at a time)
  jobs:
    - integration-tests
    - security-scan
  trigger_events:
    - patchset-created
  approval_labels:
    - name: "Code-Review"
      value: 2                        # Gate requires +2 approval

report:
  name: "Post-Merge Report"
  type: report                        # Runs AFTER merge
  window_size: 10
  jobs:
    - publish-docs
    - deploy-staging
```

### jobs.yaml
```yaml
lint:
  name: "Code Linting"
  timeout: 300                        # 5 minutes
  playbook: playbooks/lint.yaml
  dependencies: []                    # No dependencies

unit-tests:
  name: "Unit Tests"
  timeout: 600                        # 10 minutes
  playbook: playbooks/test.yaml
  dependencies: []

integration-tests:
  name: "Integration Tests"
  timeout: 1800                       # 30 minutes
  playbook: playbooks/integration.yaml
  dependencies:
    - lint
    - unit-tests
```

---

## State Transitions

### Change State Machine

```
                          ┌──────────┐
                          │   NEW    │
                          └────┬─────┘
                               │
                    (addEvent called)
                               │
                               ▼
                          ┌──────────┐
                 ┌────────│ QUEUED   │────────┐
                 │        └────┬─────┘        │
                 │             │              │
          (window full) (dequeued &    (approval denied)
                 │      window open)         │
                 │             │              ▼
                 │             ▼         ┌──────────┐
                 │        ┌──────────┐   │ ABANDONED│
                 │        │PROCESSING├───┤ (skip to │
                 │        └──┬───┬───┘   │  Gerrit) │
                 │            │   │      └──────────┘
         (window closes) │   │
                 │   (jobs done)
                 │        │   │
        ┌────────▼─┐  ┌───▼───▼────┐
        │ QUEUED   │  │ COMPLETED   │
        │ (later)  │  │ (success)   │
        └──────────┘  └─────────────┘
                          │
                    (if Gate pipeline)
                          │
                    (trigger merge)
```

### Change State to Redis

```python
{
  "change_id": "12345",
  "project_name": "my-project",
  "branch": "main",
  "state": "queued",           # NEW | QUEUED | PROCESSING | COMPLETED | FAILED | ABANDONED
  "buildsets": [
    "buildset-uuid-1",         # First gate attempt
    "buildset-uuid-2",         # Retry
  ],
  "queue_position": 1,         # Position in pipeline queue
  "created_at": "ISO timestamp"
}
```

---

## Thread Communication

### Event Queue (SchedulerQueue)

```python
# GerritEventProcessor thread:
scheduler.addEvent(enriched_event)
# → Puts event into SchedulerQueue.event_queue with 5s timeout
# → May drop event if queue full (logs error)

# SchedulerQueue thread:
event = self.event_queue.get(timeout=1)
# → Blocks up to 1 second waiting for event
# → Processes event: approvals, routing, enqueuing
# → Returns to waiting on next event
```

### Redis Communication (All Threads)

```python
# Thread A: Enqueue change to pipeline
redis.queue_enqueue("torri:pipeline:check:queue", "12345")

# Thread B: Monitor queue length
length = redis.queue_length("torri:pipeline:check:queue")

# Thread C: Dequeue for processing
change_id = redis.queue_dequeue("torri:pipeline:check:queue")
```

All Redis operations are thread-safe (Redis is single-threaded, operations are atomic).

---

## Window & Concurrency

### Window Size

Limits how many changes can be processed concurrently in a pipeline.

```yaml
pipelines:
  check:
    window_size: 5      # Up to 5 changes running jobs simultaneously
  gate:
    window_size: 1      # Only 1 change at a time (serial)
  report:
    window_size: 10     # Up to 10 in parallel
```

### Window State in Redis

```python
{
  "size": 5,            # Maximum concurrent
  "active": 2,          # Currently running
  "updated_at": "ISO"
}

# Can enqueue when: active < size
# When job completes: active -= 1 (and next change can dequeue)
```

---

## Error Handling

### Approval Denied
```
SchedulerQueue detects missing required label
→ Log: "Change 12345 approval denied: Code-Review needs +1, currently 0"
→ Post message to Gerrit: "Not ready: missing approval..."
→ Change marked ABANDONED
→ Skip all pipelines
```

### Change Not Found
```
GerritEventProcessor calls getChange(12345)
→ Gerrit API returns 404
→ Retry with exponential backoff
→ Finally: Log error, skip event
```

### Approval Verifier Error
```
Network issue checking labels
→ Catch exception
→ Return: (False, "Error checking approvals: ...")
→ Post message to Gerrit
→ Change marked ABANDONED
```

### Redis Connection Error
```
TorriRedis()
→ redis.ping() fails during __init__
→ Raise exception
→ SchedulerQueue fails to start
→ Critical error logged
```

---

## Key Features

### 1. Distributed Locks
```python
acquired = redis.acquire_lock("torri:lock:pipeline:gate", timeout=30)
if acquired:
    try:
        # Exclusive access to gate pipeline
        # Only one component can do this at a time
    finally:
        redis.release_lock("torri:lock:pipeline:gate")
```

### 2. Change Tracking
```python
# Every change has state in Redis
# Persists across scheduler restarts
redis.get_state("torri:change:12345:state")
# → Returns complete change info even if change processing ongoing
```

### 3. Pipeline Isolation
```python
# Each pipeline independent
# Check pipeline enqueues to: torri:pipeline:check:queue
# Gate pipeline enqueues to: torri:pipeline:gate:queue
# No cross-contamination
```

### 4. Daemon Threads
```
All threads are daemon=True
→ Scheduler can exit gracefully without waiting for threads
→ Threads are supporting components, not blocking
→ On shutdown: all threads terminate within 1-2 seconds
```

---

## Summary

**The flow is:**

1. **Kafka feeds events** → KafkaConnection buffers them
2. **GerritEventProcessor enriches** them with full change details
3. **SchedulerQueue routes** them to appropriate pipelines based on:
   - Project configuration
   - Required approval labels
   - Current labels on change
4. **Pipelines manage** queues and concurrency windows in Redis
5. **Changes persist** their state in Redis for tracking across restarts
6. **Future components** (executors, merger) will poll queues and process changes

Everything is **thread-safe**, **event-driven**, and **configurable via YAML**.
