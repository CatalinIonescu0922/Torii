# Torri Scheduler Implementation

Complete scheduler implementation for the Torri CI/CD system. Event-driven, multi-instance architecture with Redis-based coordination.

## Overview

The scheduler is responsible for:

1. **Event Processing**: Receiving Gerrit webhooks and normalizing Kafka events
2. **Approval Verification**: Checking labels before allowing changes into pipelines
3. **Pipeline Management**: Maintaining queues, controlling window sizes, tracking progress
4. **Job Coordination**: Scheduling jobs (execution delegated to executor service)
5. **Gerrit Feedback**: Posting comments and voting labels at each stage
6. **Real-Time UI Updates**: Broadcasting events via WebSocket and Redis Pub/Sub

## Architecture

### Single-Threaded Per Instance, Multi-Instance Deployment

```
┌─────────────────┐
│ Scheduler-1     │  Single-threaded event loop
│ • Fast         │  • Consistent state
│ • Simple       │  • Debuggable
└────────┬────────┘
         │
         │ Redis locks + shared state
         │
┌────────▼────────┐
│    Redis        │  Source of truth for all state
│ • Pipelines    │  • Locks coordinate multi-instance
│ • Queues       │  • Pub/Sub broadcasts UI updates
│ • Job state    │
└──────────┬──────┘
           │
       ┌───┴───┐
       │       │
┌──────▼──┐  ┌─▼──────┐
│Schedule │  │Scheduler│  Multiple instances process in parallel
│   -2    │  │   -3    │  • Each acquires pipeline lock
└─────────┘  └─────────┘  • Fair round-robin scheduling
```

### Components

```
scheduler/
├── redis_client.py           # Async Redis wrapper
│                             # • Locks, queues, state
│                             # • Pub/Sub for broadcasts
│
├── config_loader.py          # YAML configuration loading
│                             # • Pydantic validation
│                             # • Cross-reference checking
│
├── gerrit_client.py          # Gerrit REST API client
│                             # • Fetch labels/change details
│                             # • Post comments
│                             # • Vote labels (+1, -1, etc)
│
├── approval_verifier.py      # Label verification
│                             # • Project-level approvals
│                             # • Pipeline-specific approvals
│                             # • Caching to avoid API calls
│
├── message_template.py       # Gerrit message generation
│                             # • Variable substitution
│                             # • Custom messages from YAML
│                             # • Estimated wait times
│
├── event_processor.py        # Event normalization
│                             # • Kafka event -> TorriEvent
│                             # • Event type routing
│                             # • Handler dispatch
│
├── pipeline_manager.py       # Pipeline queue management
│                             # • Base class: BasePipelineManager
│                             # • CheckPipeline (no merge)
│                             # • GatePipeline (can merge)
│                             # • ReportPipeline (post-merge)
│                             # • Queue + window management
│                             # • Job tracking
│
└── server.py                 # FastAPI scheduler server
                              # • Main event loop
                              # • HTTP endpoints
                              # • WebSocket real-time updates
                              # • Event handler registration
```

## Configuration Files

Three YAML files define the CI/CD behavior:

### projects.yaml
Defines per-project settings:
```yaml
projects:
  test-project:
    merge_strategy: merge
    approval_labels:
      - name: code-review
        value: 1
        blocking: true
    pipelines:
      - check
      - gate
      - report
```

### pipelines.yaml
Defines pipeline behaviors:
```yaml
pipelines:
  check:
    type: check
    trigger_events: [patchset-created, change-updated]
    jobs: [lint-code, unit-tests]
    window_size: 5
    gerrit_messages:
      enqueued: "Enqueued to {pipeline_name} at position {position}"
      started: "Running: {jobs}"
      success: "✓ Passed!"
      failure: "✗ Failed: {failed_jobs}"
```

### jobs.yaml
Defines job specifications:
```yaml
jobs:
  lint-code:
    timeout: 300
    playbook: playbooks/lint.yaml
    dependencies: []
    allow_failure: false
```

## State Management (Redis Keys)

All state persisted in Redis for crash recovery and multi-instance coordination:

```
torri:pipeline:PIPELINE_ID:queue
  → List of change IDs waiting (FIFO order)

torri:pipeline:PIPELINE_ID:window
  → {size: 5, active: 2, updated_at: timestamp}

torri:change:CHANGE_ID:state
  → {state: queued, buildsets: [BS1, BS2], ...}

torri:buildset:BUILDSET_ID:state
  → {status: running, jobs: {...}, attempt: 1, ...}

torri:job:JOB_ID:state
  → {status: running, buildset_id: BS1, started_at: ...}

torri:lock:pipeline:PIPELINE_ID
  → Lock held by scheduler instance (with TTL)

torri:lock:global:merge
  → Global merge lock (only one merge at a time)

torri:event-queue
  → Events waiting for processing
```

## HTTP Endpoints

### GET /api/v1/health
Health check

### GET /api/v1/pipelines
Get all pipelines with status:
```json
{
  "pipelines": [
    {
      "id": "check",
      "name": "Check Pipeline",
      "type": "check",
      "queue_length": 5,
      "active_count": 2,
      "window_size": 5
    }
  ]
}
```

### GET /api/v1/pipelines/{pipeline_id}/queue
Get items in a pipeline queue

### GET /api/v1/changes/{change_id}
Get status of a specific change

### WS /ws/realtime/ui:events
WebSocket for real-time UI updates via Redis Pub/Sub

## Event Flow

### Normal Change: New Patchset

```
1. Developer pushes patchset
   └─ Gerrit webhook → Kafka gerrit-events topic

2. Scheduler consumes event
   ├─ Normalize to TorriEvent
   └─ Call event handlers

3. _handle_patchset_created
   ├─ Get project pipelines
   ├─ For each pipeline:
   │  ├─ Check approvals via ApprovalVerifier
   │  ├─ If approved:
   │  │  ├─ Enqueue to pipeline
   │  │  └─ Post "Enqueued at position N" to Gerrit
   │  └─ If not approved:
   │     └─ Post "Need approval X" to Gerrit

4. Main event loop: for each pipeline
   ├─ Acquire lock (distributed)
   ├─ Check if window allows
   ├─ Dequeue change
   ├─ Create buildset
   ├─ Post "Started" message
   ├─ Publish ui:events (WebSocket notifies clients)
   └─ TODO: Dispatch jobs to executor
```

### Job Completion

```
1. Executor finishes job
   └─ Kafka job-results topic

2. Scheduler processes job event
   ├─ Update job state in Redis
   ├─ Check if all jobs in buildset done
   └─ If all done:
      ├─ Check success/failure
      ├─ Post result message
      ├─ If gate pipeline passed:
      │  └─ Trigger merge (TODO)
      └─ Publish ui:events
```

### Merge Success

```
1. Merger finishes merge
   └─ Kafka merger-responses topic

2. Scheduler processes merge event
   ├─ Post "Merged successfully" to Gerrit
   ├─ Vote verified +1
   ├─ Enqueue to report pipeline
   └─ Publish ui:events
```

## Running the Scheduler

### Docker Compose

```bash
# Build
docker build -t torri-scheduler -f compose/Dockerfile --target scheduler .

# Run with docker-compose
docker-compose -f compose/compose.yaml up scheduler
```

### Local Development

```bash
# Setup environment
cp .env.scheduler.example .env.scheduler
# Edit .env.scheduler with your settings

# Install dependencies
cd microservices/Shared
pip install -e .
cd ../Torri
pip install -e .

# Run scheduler
TORRI_CONFIG_DIR=/path/to/config python -m torri.cmd.scheduler
```

### Configuration

1. Copy example YAML files:
```bash
cp SCHEDULER_EXAMPLE_*.yaml /app/config/layout/
```

2. Edit YAML files:
- `projects.yaml`: Define your projects
- `pipelines.yaml`: Define pipeline behaviors
- `jobs.yaml`: Define jobs

3. Set environment variables:
```bash
export GERRIT_URL=http://gerrit:8080
export GERRIT_USER=admin
export GERRIT_PASSWORD=secret
export REDIS_URL=redis://redis:6379/0
export KAFKA_SERVER=kafka:9094
export TORRI_CONFIG_DIR=/app/config/layout
```

## Key Design Decisions

### 1. Single-Threaded Per Instance

**Why**: Consistency, simplicity, debuggability

**How it works**:
- Each scheduler keeps events in order
- No internal race conditions
- Reproducible execution
- Multiple instances handle parallelism via Redis locks

### 2. Redis as Source of Truth

**Why**: Crash recovery, multi-instance coordination

**What it stores**:
- All queue state
- All job/buildset tracking
- Lock state
- Change state

**Recovery**:
- If scheduler crashes, another instance acquires lock and resumes
- Lock has TTL, auto-releases after 30s
- State fully persisted, no data loss

### 3. Approval Verification Before Enqueue

**Why**: Prevent wasted resources

**How it works**:
- Change arrives with patchset
- Check labels before enqueueing  
- If unapproved: Post message, don't enqueue
- If approved: Enqueue, post message
- User sees clear feedback in Gerrit

### 4. Message Templates from YAML

**Why**: Customizable, admin-friendly

**How it works**:
- Each pipeline defines messages for each stage
- Messages support variable substitution
- {position}, {estimated_time}, {failed_jobs}, etc.
- No code changes needed to customize messages

### 5. Window-Based Concurrency

**Why**: Control parallelism per pipeline

**How it works**:
- Each pipeline has window_size (default 1)
- Can't dequeue if active_count >= window_size
- Check pipeline: window=5 (parallel linting)
- Gate pipeline: window=1 (serial merge safety)
- Report pipeline: window=3 (moderate parallelism)

## Future Work

1. **Job Dispatching** (Not implemented yet)
   - Actually dispatch jobs to executor
   - Track job execution
   - Stream logs

2. **Merge Coordination**
   - Global merge lock implementation
   - Speculative merge attempts
   - Rebase conflict detection

3. **Advanced Features**
   - Dynamic window sizing
   - Priority queuing
   - Dependency trees across pipelines
   - Automatic retry on transient failure

4. **Monitoring**
   - Prometheus metrics
   - Queue depth tracking
   - Job duration histograms
   - Alerts on failure rates

## Testing

```bash
# Run scheduler
python -m pytest tests/scheduler/ -v

# Integration test with real Gerrit, Kafka, Redis
python -m pytest tests/scheduler/integration -v

# Load testing
python -m pytest tests/scheduler/load -v
```

## Common Patterns

### Add a New Pipeline Type

```python
# In pipeline_manager.py

class CustomPipeline(BasePipelineManager):
    async def on_event(self, event_data):
        # Handle events
        pass
    
    def should_merge(self):
        return True  # or False
```

### Custom Approval Labels

```yaml
# In projects.yaml

my-project:
  approval_labels:
    - name: custom-approval
      value: 2
      blocking: true
```

### Custom Messages

```yaml
# In pipelines.yaml

custom-pipeline:
  gerrit_messages:
    success: "✓ Custom message: {variable_name}"
```

## Troubleshooting

### Change not enqueueing

1. Check approvals: `curl http://gerrit:8080/a/changes/12345/detail`
2. Check config is loaded: `curl http://localhost:8000/api/v1/pipelines`
3. Check scheduler logs: `docker logs torri-scheduler`

### Messages not appearing in Gerrit

1. Check Gerrit credentials: `.env.scheduler`
2. Check GERRIT_URL: `curl http://GERRIT_URL/a/changes`
3. Check Gerrit permissions (user must have access)

### Queue growing unbounded

1. Check if jobs are dispatching (executor running?)
2. Check job completion events reaching Kafka
3. Check window sizes in pipelines.yaml

## References

- [TORRI_COMPREHENSIVE_IMPLEMENTATION.md](TORRI_COMPREHENSIVE_IMPLEMENTATION.md) - Architecture overview
- [MULTI_SCHEDULER_EXPLANATION.md](MULTI_SCHEDULER_EXPLANATION.md) - Multi-instance coordination
- [.env.scheduler.example](.env.scheduler.example) - Configuration template
