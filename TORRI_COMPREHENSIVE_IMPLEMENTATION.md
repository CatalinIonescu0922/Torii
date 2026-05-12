# Torri Scheduler: Comprehensive Implementation Guide
## Event-Driven CI/CD with Multi-Scheduler, Redis, Kafka, and Gerrit Integration

**Complete architecture covering all aspects in one place.**

---

## Table of Contents

1. [System Architecture Overview](#system-architecture-overview)
2. [Multi-Scheduler Coordination](#multi-scheduler-coordination)
3. [Configuration Management](#configuration-management)
4. [Label & Approval Verification](#label--approval-verification)
5. [Gerrit Integration & Messaging](#gerrit-integration--messaging)
6. [Event Processing Flow](#event-processing-flow)
7. [Implementation Components](#implementation-components)
8. [Operational Scenarios](#operational-scenarios)

---

## System Architecture Overview

### Core Technology Stack

```
Frontend (Web UI)
    ├─ React + TypeScript (Vite)
    └─ Real-time updates via WebSocket

API Layer
    ├─ FastAPI (Python 3.10+)
    ├─ Multiple Scheduler Instances (horizontal scaling)
    └─ Async/await patterns

Message Bus
    ├─ Apache Kafka (KRaft mode)
    ├─ Event streaming (gerrit-events, job-results)
    └─ Distributed log (audit trail)

State Management
    ├─ Redis (replacing ZooKeeper)
    ├─ Distributed locks (pipeline coordination)
    ├─ Pipeline queues (FIFO ordering)
    └─ Change/job state (source of truth)

Version Control Gate
    ├─ Gerrit (code review)
    ├─ Approval labels (verified, code-review)
    └─ Change metadata

Execution Services
    ├─ Merger (speculative merges, git operations)
    ├─ Executor (runs jobs, reports results)
    └─ Launcher (provisions resources)

Configuration
    ├─ YAML-based (declarative)
    ├─ projects.yaml (per-project config)
    ├─ pipelines.yaml (pipeline definitions)
    └─ jobs.yaml (job specifications)
```

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                  Gerrit Event Source                     │
│        (patchset-created, change-updated, etc)          │
└───────────────────┬─────────────────────────────────────┘
                    │ Webhook
                    ▼
         ┌──────────────────────┐
         │   Kafka (Event Log)  │
         │                      │
         │ • gerrit-events      │
         │ • scheduler-trigger  │
         │ • job-results        │
         │ • merger-responses   │
         └──────────┬───────────┘
                    │
         ┌──────────▼──────────┐
         │ Configuration Load  │
         │ • Validate YAML     │
         │ • Load projects     │
         │ • Load pipelines    │
         │ • Load jobs         │
         └────────┬────────────┘
                  │
    ┌─────────────▼──────────────────┐
    │  Multiple Scheduler Instances  │
    │                                │
    │ ┌──────────────────────────┐   │
    │ │ Scheduler-1 Instance     │   │
    │ │ - Single-threaded loop   │   │
    │ │ - Process events         │   │
    │ │ - Acquire locks          │   │
    │ │ - Coordinate merges      │   │
    │ │ - Broadcast via Pub/Sub  │   │
    │ └──────────────────────────┘   │
    │                                │
    │ ┌──────────────────────────┐   │
    │ │ Scheduler-2 Instance     │   │
    │ │ (Same pattern...)        │   │
    │ └──────────────────────────┘   │
    │                                │
    │ ┌──────────────────────────┐   │
    │ │ Scheduler-3 Instance     │   │
    │ │ (Same pattern...)        │   │
    │ └──────────────────────────┘   │
    └────────┬───────────────────────┘
             │
    ┌────────▼──────────────┐
    │   Redis (State DB)    │
    │                       │
    │ Coordination:         │
    │ • Distributed locks   │
    │ • Pipeline queues     │
    │ • Change state        │
    │ • Job tracking        │
    │ • Build sets          │
    │ • Pub/Sub channels    │
    └────────┬──────────────┘
             │
    ┌────────▼──────────────────────────┐
    │   Execution & Integration         │
    │                                   │
    │ ┌─────────────────────────────┐   │
    │ │ Merger Service              │   │
    │ │ - Git operations            │   │
    │ │ - Speculative merges        │   │
    │ │ - Atomic merge execution    │   │
    │ └─────────────────────────────┘   │
    │                                   │
    │ ┌─────────────────────────────┐   │
    │ │ Executor Service            │   │
    │ │ - Job execution             │   │
    │ │ - Log streaming             │   │
    │ │ - Result reporting          │   │
    │ └─────────────────────────────┘   │
    │                                   │
    │ ┌─────────────────────────────┐   │
    │ │ Gerrit Integration          │   │
    │ │ - Post comments             │   │
    │ │ - Vote labels (+1, -1)      │   │
    │ │ - Fetch change state        │   │
    │ └─────────────────────────────┘   │
    └────────────────────────────────────┘
```

---

## Multi-Scheduler Coordination

### Why Single-Threaded Per Instance

Each scheduler instance is **single-threaded** within its event loop, meaning:

- ✅ **Consistency**: Events processed sequentially, no internal race conditions
- ✅ **Simplicity**: No complex locking within scheduler
- ✅ **Debuggability**: Reproducible execution order

However, **multiple instances run in parallel**:

- ✅ **Scalability**: Handle 10+ pipelines across multiple schedulers
- ✅ **HA**: If one crashes, others continue
- ✅ **Throughput**: Process multiple changes simultaneously

### Coordination Mechanisms

#### 1. **Distributed Locks (Redis)**

Each pipeline has a Redis lock to prevent concurrent processing:

```
Lock Owner Timeline:

Scheduler-1: [Acquire lock "pipeline:check"] → [Process changes] → [Release]
                ↓
Scheduler-2: [Wait blocked] ← [Waiting...] → [Acquire lock] → [Process] → [Release]
                ↓
Scheduler-3: [Still waiting] ← [Blocked...] → [Waiting...] → [Acquire] → [Process]

Result: Serial execution per pipeline + parallel across pipelines
```

- **Timeout**: Each lock has expiration (e.g., 30 seconds)
- **Auto-Release**: If scheduler crashes, lock auto-releases after timeout
- **No Starvation**: All schedulers get fair turns

#### 2. **Global Merge Lock**

Only ONE merge happens at a time globally (prevents git conflicts):

```
All Schedulers trying to merge simultaneously:

S1: [Hold MERGE_LOCK] → [Git merge happens atomically] → [Release]
S2: [Blocked...] → [Blocked...] → [Can acquire now]
S3: [Blocked...] → [Blocked...] → [Can acquire now]

Only S1's merge succeeds, then S2, then S3
```

#### 3. **Redis Pub/Sub Broadcasting**

Any scheduler can publish events to all clients:

```
Event Published by Scheduler-1:
    ↓
Redis Pub/Sub Channel: "ui:events"
    ↓
All Connected WebSocket Clients Receive Update Instantly:
    ├─ Browser Client 1: Update
    ├─ Browser Client 2: Update
    ├─ Browser Client 3: Update
    └─ Browser Client N: Update

Key: Works with ANY scheduler instance publishing
```

#### 4. **Source of Truth: Redis**

All state stored in Redis (not local memory):

```
Change State Flow:

Scheduler-1 processes:
    ├─ Reads change state from Redis
    ├─ Updates change state in Redis
    ├─ Publishes to Pub/Sub
    └─ Other schedulers see updated state

Scheduler-2 checks state:
    ├─ Reads from same Redis instance
    ├─ Sees S1's updates
    ├─ Makes decisions based on latest state
    └─ No stale data, no caching issues

Result: Perfect consistency across all instances
```

---

## Configuration Management

### YAML Configuration Hierarchy

```
Three Layers of Configuration:

LAYER 1: projects.yaml
├─ Definition: Per-project settings
├─ Content:
│  ├─ Merge strategy (merge, rebase, squash)
│  ├─ Required approval labels
│  └─ Which pipelines apply
│
LAYER 2: pipelines.yaml
├─ Definition: Pipeline definitions
├─ Content:
│  ├─ Pipeline ID & name
│  ├─ Pipeline type (check, gate, report)
│  ├─ Trigger events (patchset-created, change-updated)
│  ├─ Jobs to run
│  ├─ Window size & parallelism
│  ├─ Approval requirements per-pipeline
│  └─ Gerrit messages (custom messages for each stage)
│
LAYER 3: jobs.yaml
├─ Definition: Job specifications
└─ Content:
   ├─ Job name & description
   ├─ Executor requirements
   ├─ Timeout & playbooks
   ├─ Variables & environment
   └─ Dependencies on other jobs
```

### Configuration Validation Process

```
Load Phase:
1. Parse YAML files (pipelines.yaml, projects.yaml, jobs.yaml)
2. Validate syntax (YAML format errors)
3. Create Pydantic models (type checking)
4. Validate business rules

Cross-Reference Phase:
1. For each project: Verify referenced pipelines exist
2. For each pipeline: Verify referenced jobs exist
3. For each job: Verify dependencies are valid
4. Check for circular dependencies

Result:
├─ Configuration loaded successfully OR
└─ Validation error (clear message, which file/line)

On Startup:
├─ Load all configs
├─ If validation passes: Use configurations
└─ If validation fails: Start with fallback or reject
```

### Configuration Access Pattern

```
Scheduler retrieves config:

1. When change arrives from Gerrit:
   scheduler.config_loader.get_pipelines_for_project(project_name)
   └─ Returns: List of pipelines that apply to this project

2. When checking approval requirements:
   scheduler.config_loader.get_project_config(project_name)
   └─ Returns: Project config with approval_labels

3. When processing pipeline:
   scheduler.config_loader.get_pipeline_config(pipeline_id)
   └─ Returns: Pipeline config with jobs and messages

All configs loaded once at startup, cached in memory
```

---

## Label & Approval Verification

### Approval Labels Concept

In Gerrit, labels are votes by reviewers:

```
Example Labels on a Change:

Label: "verified"
├─ Value -1: Failed (CI couldn't verify)
├─ Value 0: Not voted
└─ Value +1: Passed (CI verified code works)

Label: "code-review"
├─ Value -2: Do not merge (blocking)
├─ Value -1: I would prefer this not merged
├─ Value 0: Not reviewed
├─ Value +1: Looks good to me
└─ Value +2: Looks good to me (approved), can merge

Project-Level Requirements:
├─ verified must be >= +1 (OR not required)
└─ code-review must be >= +1 (OR >= +2 depending on config)

Pipeline-Level Requirements:
├─ Gate pipeline might require verified +1 before enqueue
└─ Security pipeline might require code-review +2
```

### Verification Flow

```
When Change Arrives:

Step 1: Fetch Current Labels from Gerrit
└─ Query Gerrit API for change details
└─ Extract current label values

Step 2: Check Project-Level Approvals
├─ Get project config
├─ Verify all required labels met
└─ If not: Reject, don't even try pipelines

Step 3: For Each Applicable Pipeline
├─ Get pipeline config
├─ Check pipeline-specific approval requirements
├─ If met: Proceed to enqueue
├─ If not: Post rejection message to Gerrit

Step 4: Enqueue or Reject
├─ Both: Post message to Gerrit (feedback to user)
└─ Enqueue: Add to pipeline queue in Redis
```

### Prevention of Unapproved Enqueuing

```
Without Verification:
┌─ Change arrives
├─ Immediately enqueued to pipeline
└─ Later fails gate, wasted resources

With Verification:
┌─ Change arrives
├─ Check approvals:
│  ├─ verified = 0 (need +1)
│  └─ code-review = +1 (OK)
├─ Result: Missing approval
├─ Post to Gerrit: "Need verified +1 to enqueue to gate"
└─ Change stays out of queue until approved

User Action:
├─ Developer requests verification from CI
├─ CI system (or human) approves
├─ Label set to verified +1
├─ Webhook triggers re-evaluation
├─ Now approved, gets enqueued
└─ Processing proceeds
```

---

## Gerrit Integration & Messaging

### Message Template System

Messages defined in YAML and customized per-pipeline:

```yaml
# From pipelines.yaml

gate:
  gerrit_messages:
    enqueued: |
      ⏳ Torri: Change enqueued in {pipeline_name}
      Position: {position}/{queue_length}
      Est. time: {estimated_time}
    
    started: |
      🚀 Torri: {pipeline_name} started
      Running: {jobs}
    
    success: |
      ✓ Torri: {pipeline_name} PASSED
      Will vote: {vote_label} {vote_value}
    
    failure: |
      ✗ Torri: {pipeline_name} FAILED
      Failed: {failed_jobs}
      Please rebase and push new patchset

Messages support variable substitution:
├─ {position} → Queue position (1, 2, 3, ...)
├─ {estimated_time} → ~10 minutes
├─ {failed_jobs} → lint, unit-tests
├─ {vote_label} → verified
└─ {vote_value} → +1
```

### Gerrit API Interactions

Scheduler interacts with Gerrit via REST API:

```
Post Comment:
├─ Endpoint: PATCH /changes/{change_id}/revisions/current/review
├─ Payload: { "message": "..." }
└─ Use Case: Inform user of status

Set Label/Vote:
├─ Endpoint: PATCH /changes/{change_id}/revisions/current/review
├─ Payload: { "labels": { "verified": 1 } }
└─ Use Case: Vote +1 after success, -1 after failure

Fetch Change Details:
├─ Endpoint: GET /changes/{change_id}/detail
├─ Returns: Full change object with current labels
└─ Use Case: Check approval status before enqueuing
```

### Message Flow Throughout Pipeline

```
Timeline of Gerrit Messages:

T0: Patchset Created
    └─ Gerrit sends webhook to scheduler

T1: Scheduler Receives Event
    ├─ Check approvals
    ├─ If missing: Post "Need approval X, Y, Z"
    └─ If approved: Proceed

T2: Change Enqueued
    └─ Post "Enqueued at position 3 of 5"

T3: Change Reaches Position 1
    └─ Dequeue and start pipeline
    ├─ Post "Pipeline started, running: lint, tests"
    └─ Begin job execution

T4-T8: Jobs Running
    ├─ Jobs execute in sequence
    └─ Logs could be posted periodically (optional)

T9: All Jobs Complete (Success)
    ├─ Post "All jobs passed!"
    ├─ State: verified +1 (label vote)
    └─ Message: "Verified by CI - ready to merge"

OR: Some Job Failed
    ├─ Post "Job X failed, see logs at:"
    ├─ State: verified -1 (fail vote)
    └─ Message: "Please fix and push new patchset"

T10: User Action
    ├─ If failed: Developer rebases and pushes new patchset
    │  └─ Webhook received, repeat from T1
    └─ If passed: Change ready for merge
       └─ Maintainer approves for merge

T11: Change Merged
    ├─ Post "Change merged successfully"
    └─ Enqueue to post-merge pipeline (docs, releases)
```

---

## Event Processing Flow

### The Main Event Loop

Each scheduler instance runs a single-threaded event loop:

```
while True:  # Main loop (infinite)
    1. Acquire pipeline lock (blocking with timeout)
       └─ Try up to 5 seconds
    
    2. Process pipeline queue
       ├─ Dequeue next change (if window available)
       ├─ Create build set (attempt record)
       ├─ Schedule jobs
       └─ Release lock
    
    3. Check for dirty pipelines
       ├─ Jobs completed, pipeline marked dirty
       ├─ Reprocess to schedule next batch
       └─ Mark clean after processing
    
    4. Process events from Kafka
       ├─ Poll gerrit-events topic
       ├─ Poll job-results topic
       ├─ Normalize to TorriEvent
       └─ Queue in Redis
    
    5. Handle broadcasts
       ├─ Publish state updates to Pub/Sub
       ├─ WebSocket clients receive instantly
       └─ UI updates in real-time

Duration: Continuous, non-blocking (except when acquiring locks)
```

### Event Types and Handlers

```
Gerrit Events:
├─ patchset-created
│  └─ Handler: Enqueue to check pipeline
├─ change-updated
│  └─ Handler: Re-run check pipeline (new patchset)
└─ change-ready
   └─ Handler: Enqueue to gate pipeline

Executor Events:
├─ job-started
│  └─ Handler: Update job state, maybe post comment
├─ job-completed
│  └─ Handler: Check all jobs in build set
│     └─ If all done, determine success/failure
└─ job-failed
   └─ Handler: Mark build set failed, requeue or reject

Merger Events:
├─ merge-started
│  └─ Handler: Update change state
├─ merge-success
│  └─ Handler: Change now merged, enqueue to post pipeline
└─ merge-failed
   └─ Handler: Retry or reject depending on reason

Scheduler Events:
├─ config-reload
│  └─ Handler: Hot-reload YAML configs
└─ scheduler-restart
   └─ Handler: Recover state from Redis, resume
```

---

## Implementation Components

### Core Modules (High-Level)

```
torri/
├── config/
│   ├── loader.py
│   │  └─ Loads & validates YAML configs
│   │  └─ Provides config access methods
│   └── models.py
│      └─ Pydantic models for validation
│
├── scheduler/
│   ├── server.py
│   │  └─ FastAPI app, /api/v1 endpoints
│   │  └─ Main event loop
│   │  └─ WebSocket handlers
│   │
│   ├── pipeline_manager.py
│   │  └─ Handles queue processing per pipeline
│   │  └─ Window sizing & adjustment
│   │  └─ Job scheduling
│   │
│   ├── event_processor.py
│   │  └─ Routes events to handlers
│   │  └─ Gerrit event normalization
│   │
│   ├── approval_verifier.py
│   │  └─ Checks if approvals met
│   │  └─ Prevents unapproved enqueue
│   │
│   ├── message_template.py
│   │  └─ Handles Gerrit message templating
│   │  └─ Variable substitution
│   │
│   ├── enqueue_handler.py
│   │  └─ Coordinates enqueue + messaging
│   │  └─ Calls approval_verifier
│   │  └─ Posts messages to Gerrit
│   │
│   ├── merge_coordinator.py
│   │  └─ Handles global merge coordination
│   │  └─ Acquires merge lock
│   │  └─ Broadcasts merge events
│   │
│   └── redis_client.py
│      └─ Async Redis wrapper
│      └─ Locks, queues, state operations
│
├── gerrit/
│   └── gerrit_client.py
│      └─ REST API client
│      └─ Post comments, set labels
│      └─ Fetch change details
│
└── connection/
    └─ Kafka consumer/producer
       └─ Connect to event sources
       └─ Receive Gerrit webhooks
```

### State Storage (Redis Keys)

```
torri:pipeline:PIPELINE_ID:queue
├─ Type: Redis List (FIFO)
└─ Contains: Change IDs waiting in queue

torri:pipeline:PIPELINE_ID:window
├─ Type: Redis Hash
└─ Contains: {size: 5, active: 2, timestamp: ...}

torri:change:CHANGE_ID:state
├─ Type: Redis String (JSON)
└─ Contains: {state, pipeline, position, builSets, ...}

torri:build-set:BUILD_SET_ID
├─ Type: Redis String (JSON)
└─ Contains: {status, jobs, startTime, endTime, ...}

torri:job:JOB_ID:state
├─ Type: Redis String (JSON)
└─ Contains: {status, result, duration, ...}

torri:job:JOB_ID:logs
├─ Type: Redis List
└─ Contains: Log lines (last 10000)

torri:lock:pipeline:PIPELINE_ID
├─ Type: Redis Lock (with TTL)
└─ Blocks other schedulers

torri:lock:global:merge
├─ Type: Redis Lock (with TTL)
└─ Blocks all merge attempts

torri:event-queue
├─ Type: Redis List
└─ Contains: Event objects for processing
```

---

## Operational Scenarios

### Scenario 1: Normal Change Flow

```
1. Developer pushes commit to refs/for/main (in Gerrit)

2. Gerrit fires patchset-created webhook

3. Scheduler receives webhook
   ├─ Check approvals: verified=0, code-review=0
   ├─ Result: Missing approvals
   └─ Post to Gerrit: "Need verified +1 and code-review +1"

4. Maintainer reviews, adds code-review +1

5. CI system (or bot) sets verified +1

6. Gerrit fires change-updated webhook (labels changed)

7. Scheduler receives webhook
   ├─ Check approvals: verified=+1, code-review=+1
   ├─ Result: Approved!
   ├─ Enqueue to gate pipeline
   └─ Post to Gerrit: "Enqueued to gate at position 3"

8. Change waits in queue (position 3)

9. Changes at positions 1-2 finish, change moves to position 1

10. Scheduler dequeues change
    ├─ Create build set
    ├─ Schedule jobs: compile, integration-tests, perf-tests
    └─ Post to Gerrit: "Gate pipeline started"

11. Jobs run sequentially (gate is serial)
    ├─ compile: PASS
    ├─ integration-tests: PASS
    └─ perf-tests: PASS

12. All jobs passed
    ├─ Build set marked SUCCESS
    ├─ Post to Gerrit: "All tests PASSED!"
    ├─ Vote: verified +1 (already was +1)
    └─ Ready for merge

13. Maintainer clicks "MERGE" in Gerrit UI

14. Gerrit fire change-merged webhook

15. Scheduler receives and enqueues to post pipeline
    ├─ Run update-docs job
    ├─ Run trigger-release job
    └─ Post to Gerrit: "Post-merge tasks running"

16. Post jobs complete, merged change is done
```

### Scenario 2: Change Fails, Developer Fixes

```
1. (Steps 1-10 same as Scenario 1)

11. Jobs run, compile FAILS
    ├─ Build set marked FAILURE
    └─ Post to Gerrit: "Compile failed, see logs:"

12. Developer sees failure message in Gerrit

13. Developer fixes code and pushes new patchset

14. Gerrit fires patchset-updated webhook

15. Scheduler receives webhook
    ├─ Create NEW build set (attempt #2)
    ├─ Schedule jobs again
    └─ Post to Gerrit: "Re-testing new patchset (attempt #2)"

16-18. Jobs run, now PASS

19. Post results to Gerrit, ready for merge

(Repeat until pass or developer gives up)
```

### Scenario 3: Multiple Schedulers, Merge Coordination

```
Setup: 3 scheduler instances, gate pipeline

T0: Change A in position 1 (S1 has pipeline lock)
    Change B in position 2
    Change C in position 3

T1: S1 starts processing Change A

T2: S2 and S3 try to process gate pipeline
    ├─ S2: Try acquire "lock:pipeline:gate" → BLOCKED
    ├─ S3: Try acquire "lock:pipeline:gate" → BLOCKED

T3-60: S1 processes Change A
    ├─ Create build set
    ├─ Schedule jobs
    ├─ Jobs run...
    ├─ All pass
    ├─ Try acquire "lock:global:merge" → SUCCESS
    ├─ Execute merge (atomic git operation)
    ├─ Release "lock:global:merge"
    ├─ Broadcast merge event to Pub/Sub
    │  └─ All UIs notified instantly
    └─ Release "lock:pipeline:gate"

T61: S2 acquires "lock:pipeline:gate"
    ├─ Queue now has [B, C]
    ├─ Dequeue B
    ├─ Start processing B
    └─ (S3 still blocked)

T120: S1 free, tries to process gate again
    ├─ Try "lock:pipeline:gate"
    ├─ S2 has it, so blocked
    └─ (Can work on other pipelines)

T180: S2 finishes B (assume failure)
    ├─ Release "lock:pipeline:gate"

T181: S3 acquires "lock:pipeline:gate"
    ├─ Dequeue C
    ├─ Process C
    └─ (S1, S2 now free)

Result: Perfect coordination with no conflicts
```

### Scenario 4: Scheduler Crash Recovery

```
Setup: Scheduler-1 crashes during merge

T0-30: S1 has "lock:global:merge", executing git merge

T31: S1 CRASHES ✗
    └─ Lock still held (TTL = 30 seconds from T0)

T32-60: S2 and S3 try merge
    ├─ S2: Try "lock:global:merge" → BLOCKED
    ├─ S3: Try "lock:global:merge" → BLOCKED

T61: Lock expires (30s TTL)
    └─ "lock:global:merge" auto-released

T62: S2 acquires "lock:global:merge"
    ├─ Check change state
    │  ├─ Is it merged already? (Check git)
    │  └─ If yes: Continue as normal
    │  └─ If no: Retry merge
    └─ Complete merge operation

T63: S2 broadcasts merge event

Result: Even with crash, no data loss, eventual consistency
```

---

## Complete Request-Response Example

### Example 1: GET Pipeline Status

```
Client Request:
├─ GET /api/v1/pipelines
└─ Returns: List of all pipelines with queue info

Scheduler Processing:
├─ Query Redis keys: "torri:pipeline:PIPELINE_ID:*"
├─ For each pipeline: Get queue length, window size, active count
└─ Return JSON

Response:
{
  "pipelines": [
    {
      "id": "check",
      "name": "Check Pipeline",
      "type": "check",
      "queue_length": 5,
      "active_count": 3,
      "window_size": 5
    },
    {
      "id": "gate",
      "name": "Gate Pipeline",
      "type": "gate",
      "queue_length": 2,
      "active_count": 1,
      "window_size": 1
    }
  ]
}
```

### Example 2: WebSocket Real-Time Updates

```
Client: Connect WebSocket to ws://localhost:8000/ws/realtime/ui:events

Server Mechanics:
├─ Accept WebSocket connection
├─ Subscribe to Redis Pub/Sub channel "ui:events"
└─ For each published message:
   ├─ Parse message
   ├─ Send to WebSocket client
   └─ Client UI updates instantly

Message Flow:
1. Scheduler-1: Change A merged
   └─ Publish to Redis: {"type": "change.merged", "change_id": "12345"}

2. Redis Pub/Sub broadcasts to:
   ├─ WebSocket client 1
   ├─ WebSocket client 2
   └─ WebSocket client 3

3. All clients receive instantly and display "✓ Change merged"
```

---

## Summary: Implementation Checklist

### Phase 1: Configuration & Loading
- [ ] Create YAML configuration files (projects, pipelines, jobs)
- [ ] Implement ConfigurationLoader with validation
- [ ] Test configuration parsing and error messages

### Phase 2: Multi-Scheduler Architecture
- [ ] Set up Redis instance
- [ ] Implement distributed locks
- [ ] Implement pipeline queues
- [ ] Test lock acquisition/release

### Phase 3: Gerrit Integration
- [ ] Implement GerritClient (REST API calls)
- [ ] Implement ApprovalVerifier
- [ ] Implement MessageTemplate system
- [ ] Set up Gerrit webhooks

### Phase 4: Event Processing
- [ ] Implement main event loop
- [ ] Implement event processor
- [ ] Integrate Kafka consumer
- [ ] Handle all event types

### Phase 5: Pipeline Management
- [ ] Implement PipelineManager
- [ ] Implement job scheduling
- [ ] Implement merge coordination
- [ ] Implement EnqueueHandler

### Phase 6: UI & Monitoring
- [ ] Implement WebSocket endpoints
- [ ] Implement Pub/Sub broadcasting
- [ ] Create monitoring dashboard
- [ ] Add detailed logging

### Phase 7: Testing & Validation
- [ ] Unit tests for each component
- [ ] Integration tests (multi-scheduler)
- [ ] Failure scenario tests
- [ ] Load testing

---

## Key Design Patterns Used

```
1. Single-Threaded Loop with Locks
   └─ Ensures consistency, enables horizontal scaling

2. Distributed Locks (Redis)
   └─ Prevents race conditions between scheduler instances

3. Source of Truth in Redis
   └─ All state persisted, recoverable after crashes

4. Pub/Sub for Broadcasting
   └─ Real-time updates to all clients

5. Template Messages from Config
   └─ User-friendly, customizable feedback

6. Async/Await Throughout
   └─ Non-blocking I/O, efficient resource usage

7. Event-Driven Architecture
   └─ Kafka as core, all components async

8. Configuration as Code
   └─ YAML-based, validated at load time

9. Approval Gate Before Processing
   └─ Prevent wasted resources on unapproved changes

10. BuildSet Immutability
    └─ Track each attempt, enable debugging
```

---

## Deployment Model

```
Development:
├─ 1 scheduler instance
├─ Redis local or Docker
├─ Kafka local or Docker
└─ YAML configs in git

Staging:
├─ 3 scheduler instances
├─ Shared Redis
├─ Shared Kafka
├─ Same configs as production
└─ Test multi-scheduler interactions

Production:
├─ 10+ scheduler instances (auto-scale)
├─ Managed Redis (AWS ElastiCache)
├─ Managed Kafka (AWS MSK)
├─ Load balancer (nginx/HAProxy)
├─ Read-only YAML configs (from git)
└─ Monitor and alert on failures
```
