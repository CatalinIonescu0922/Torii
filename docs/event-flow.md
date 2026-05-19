# Event Flow: From Gerrit to Pipeline Completion

This document traces the full lifecycle of a Gerrit event through the Torii system, from the moment Gerrit emits it to the final status update served to the UI.

---

## Overview

```
Gerrit
  └─► Kafka (gerrit-stream-events)
        └─► KafkaConnection  ──────────────────────────────────────────────── thread
              └─► GerritEventProcessor  ──────────────────────────────────── thread
                    ├─► Gerrit REST API (enrich)
                    └─► Kafka (trigger-events)
                          └─► TriggerBridge (main())  ────────────────────── thread
                                └─► SchedulerQueue  ──────────────────────── thread
                                      ├─► _change_meets_requirements()
                                      ├─► pipeline.enqueue_change()  ──────── Redis
                                      ├─► request_merge()  ─────────────────── thread
                                      │     └─► Kafka (merger-requests)
                                      │           └─► Merger service
                                      │                 └─► Kafka (merger-responses)
                                      │                       └─► on_merge_done()
                                      │                             └─► launch_jobs()  ── threads (one per job)
                                      │                                   └─► on_done()
                                      │                                         ├─► gerrit.set_review()
                                      │                                         └─► refresh_status()
                                      └─► refresh_status()
                                              └─► Redis (torri:ui:status)
                                                    └─► StatusAPI GET /api/status
                                                          └─► React Dashboard
```

---

## Stage 1 — Gerrit Emits the Event

Gerrit's Kafka plugin watches for activity on the server and publishes raw JSON events to the `gerrit-stream-events` topic.

**Example raw event (patchset-created):**
```json
{
  "type": "patchset-created",
  "change": {
    "project": "libraries/common-utils",
    "branch": "main",
    "number": 123
  },
  "patchSet": {
    "number": 1,
    "ref": "refs/changes/23/123/1"
  }
}
```

**Known event types:**
- `patchset-created`
- `comment-added`
- `change-merged`
- `change-abandoned`
- `change-restored`
- `ref-updated`
- `wip-state-changed`
- `private-state-changed`
- `reviewer-added`

---

## Stage 2 — KafkaConnection Polls the Raw Event

**File:** `microservices/Torri/src/torri/kafka/kafka_client.py`  
**Class:** `KafkaConnection(threading.Thread)`

`KafkaConnection` runs in its own thread, polling Kafka continuously.

**Consumer config:**
| Setting | Value |
|---|---|
| `bootstrap.servers` | `KAFKA_SERVER` env var (default: `localhost:9094`) |
| `group.id` | `events-consumer-group` |
| `auto.offset.reset` | `earliest` |
| `enable.auto.commit` | `False` (manual commit) |
| `max.poll.interval.ms` | `300000` |

**What happens:**
1. `connect()` initializes the consumer and subscribes to `gerrit-stream-events`, then spawns the polling thread.
2. `get_events()` polls Kafka with a 1.0-second timeout in a tight loop.
3. Each message is deserialized from UTF-8 JSON into a Python dict.
4. The dict is placed into `event_queue` (an unbounded `queue.Queue`).
5. The loop continues polling.

`GerritEventProcessor` reads from this queue by calling `kafka_connection.getEvent()`. Once it is done with an event it calls `eventDone()`, which commits the Kafka offset.

---

## Stage 3 — GerritEventProcessor Parses and Enriches

**File:** `microservices/Torri/src/torri/gerrit/gerritconnection.py`  
**Class:** `GerritEventProcessor(threading.Thread)`

Runs in its own thread, consuming from `KafkaConnection.event_queue`.

### Step 3a — Parse the raw dict into a GerritTriggerEvent

`_build_event(data)` reads the raw Kafka dict and produces a typed object:

```python
class GerritTriggerEvent:
    type: str           # "patchset-created"
    project_name: str   # "libraries/common-utils"
    branch: str         # "main"
    change_number: str  # "123"
    patch_number: str   # "1"
    ref: str            # "refs/changes/23/123/1"
    comment: str
    oldrev: str
    newrev: str
```

If `type` is unknown the event is dropped. If the comment starts with `[Torii]` the event is ignored to avoid feedback loops.

### Step 3b — Enrich the change via Gerrit REST API

If the event has a `change_number`, enrichment is submitted to a `ThreadPoolExecutor(max_workers=5)`:

```
gerrit_connection.getChange(change_number, refresh=True)
```

**What `getChange` does:**
1. Checks Redis for a cached `GerritChange` (keyed `torri:change:{number}`). Skipped if `refresh=True`.
2. Coordinates with a network manager to prevent multiple threads from fetching the same change simultaneously.
3. Calls Gerrit REST:
   ```
   GET /a/changes/{number}?o=DETAILED_LABELS&o=CURRENT_REVISION&o=ALL_REVISIONS&...
   ```
4. Builds a `GerritChange` from the response:
   ```python
   class GerritChange:
       number: int
       patchset: int
       project: str
       branch: str
       status: str       # NEW, MERGED, ABANDONED
       subject: str
       author: str
       url: str
       labels: Dict[str, int]   # {"Code-Review": 2, "Verified": 1}
       current_revision: dict
       needs_changes: List[GerritChange]
       needed_by_changes: List[GerritChange]
   ```
5. Caches the result in Redis:
   - `torri:change:{number}` — latest patchset (pickle, 7-day TTL)
   - `torri:change:{number}:{patchset}` — versioned (pickle, 7-day TTL)
6. Signals any waiting threads via `threading.Event`.

### Step 3c — Publish to trigger-events

Once enrichment completes, `_on_enrichment_done` calls `_dispatch_event(event)`, which serialises the `GerritTriggerEvent` to JSON and publishes it to the `trigger-events` Kafka topic (key = project name).

---

## Stage 4 — TriggerBridge Hands Off to the Scheduler

**File:** `microservices/Torri/src/torri/cmd/scheduler.py`  
**Function:** `_trigger_bridge()`

A second `KafkaConnection` subscribes to `trigger-events`. For each message it:
1. Deserializes to a `GerritTriggerEvent` via `GerritTriggerEvent.from_dict(data)`.
2. Calls `scheduler_queue.addEvent(event)` to push the event into the scheduler's internal queue.

---

## Stage 5 — SchedulerQueue Routes the Event

**File:** `microservices/Torri/src/torri/scheduler/scheduler_queue.py`  
**Class:** `SchedulerQueue(threading.Thread)`

Runs in its own thread with a simple loop:

```python
while self.running:
    event = self.event_queue.get(timeout=1)
    self._process_event(event)
```

### Initialization: `_initialize_pipelines()`

On startup the scheduler loads two YAML files:

**pipelines.yaml** — parsed by `PipelineConfigLoader`:
```yaml
pipelines:
  - pipeline:
      name: check
      manager: independent
      require:
        open: true
        current-patchset: true
        approval:
          - code-review: 2
      reject:
        approval:
          - integrated: [-2, -1]
      trigger:
        gerrit:
          - event: patchset-created
      success:
        gerrit:
          - Verified: 1
      failure:
        gerrit:
          - Verified: -1
```

Each pipeline entry produces a `PipelineConfig` object and an `IndependentPipeline` or `DependentPipeline` manager instance stored in `self.pipelines[name]`.

**projects.yaml** — parsed directly:
```yaml
projects:
  - project:
      name: libraries/common-utils
      branches:
        - main
      merge-mode: cherry-pick
      check:
        jobs:
          - unit-tests
```

Builds two dicts:
- `project_pipelines[project]` → list of pipeline names
- `project_pipeline_jobs[(project, pipeline)]` → list of job names

### `_process_event(event)` — step by step

**1. Find applicable pipelines**

```python
pipeline_names = self.project_pipelines.get(event.project_name, [])
```
If the project is not in `projects.yaml` the event is silently dropped.

**2. For each pipeline — check the trigger event type**

```python
trigger_events = [t["event"] for t in pipeline_config.trigger["gerrit"]]
if event.type not in trigger_events:
    continue
```

**3. Validate the change**

`_change_meets_requirements(event, pipeline_config)` fetches the `GerritChange` from the Redis cache (via `GerritSource.getChange()`) and runs these checks in order:

| Check | Condition to pass |
|---|---|
| `require_open` | `change.status == "NEW"` |
| `require_current_patchset` | `event.patch_number == str(change.patchset)` |
| Required approvals | e.g. `labels["Code-Review"] >= 2` |
| Reject approvals | e.g. `labels["Integrated"]` is NOT in `[-2, -1]` |

Returns `(True, "")` on pass or `(False, reason)` on failure.

**4. Duplicate guard**

```python
start_key = f"torri:started:{pipeline_name}:{change_id}:{event.patch_number}"
already_started = not self.redis.client.setnx(start_key, "1")
```

`SETNX` is atomic — only the first thread sets the key. Replayed events from Kafka are dropped here.

**5. Enqueue to pipeline**

```python
pipeline.enqueue_change(change_id)
# Appends change_id to Redis list: torri:pipeline:{pipeline_name}:queue
```

**6. Post start comment (if configured)**

```python
gerrit_conn.set_review(change_id, patch_number, message=pipeline_config.start_message)
# POST /a/changes/{change}/revisions/{patchset}/review
```

**7. Refresh UI status snapshot**

```python
refresh_status(redis, list(pipeline_configs.keys()))
```

See Stage 9 for what this does.

**8. Request speculative merge**

```python
request_merge(
    job_id=f"{pipeline_name}:{change_id}:{patch_number}",
    project=f"{gerrit_conn.base_url}/{project_name}",
    branch=branch,
    patchset_refs=[event.ref],
    on_done=on_merge_done,
)
```

---

## Stage 6 — Speculative Merge

**File:** `microservices/Torri/src/torri/scheduler/merger_client.py`  
**Function:** `request_merge()`

Spawns a daemon thread (`_merge_worker`) that:

1. Publishes a merge request to Kafka topic `merger-requests`:
   ```json
   {
     "job_id": "check:123:1",
     "target_repository": "http://gerrit:8080/libraries/common-utils",
     "base_branch": "main",
     "patchset_refs": ["refs/changes/23/123/1"],
     "action": "SPECULATIVE_MERGE"
   }
   ```

2. Polls `merger-responses` for up to 120 seconds, looking for the matching `job_id`.

3. On success, extracts `merged_commit_hash` and calls `on_done(merged_ref, None)`.

4. On timeout or failure, calls `on_done(None, error_message)`.

The Merger service (separate container) handles the actual git operations and writes the response back.

---

## Stage 7 — Merge Completion Callback

**Callback:** `on_merge_done(synthetic_ref, error)` defined in `scheduler_queue.py`

- **If error:** logs the failure, calls `on_done(False)` to mark the pipeline run as failed.
- **If success:** calls `launch_jobs(change_id, pipeline_name, job_names, redis, on_done, synthetic_ref=synthetic_ref)`.

---

## Stage 8 — Job Execution

**File:** `microservices/Torri/src/torri/scheduler/job_runner.py`  
**Function:** `launch_jobs()`

One thread is spawned per job. Each thread runs `_run_job()`.

**On job start**, initial state is written to Redis:
```
Key:   torri:job:{pipeline_name}:{change_id}:{job_name}
Value: {
  "job_id": "check:123:unit-tests:a1b2c3",
  "job_name": "unit-tests",
  "change_id": "123",
  "pipeline_name": "check",
  "status": "running",
  "start_time": "2026-05-16T14:32:00+00:00",
  "synthetic_ref": "abc123..."
}
```

**Mock execution (current):** sleeps `JOB_DURATION_SECONDS` (50 seconds).

**On job completion**, state is updated:
```
"status": "success",
"end_time": "2026-05-16T14:32:50+00:00"
```

A shared counter tracks remaining jobs. When all jobs finish, `on_done(succeeded)` is called.

---

## Stage 9 — Pipeline Completion Callback

**Callback:** `on_done(succeeded)` defined in `scheduler_queue.py`

**1. Post Gerrit vote**

```python
labels = pipeline_config.success_labels if succeeded else pipeline_config.failure_labels
gerrit_conn.set_review(change_id, patch_number, message=message, labels=labels)
# Example: labels={"Verified": 1} on success, {"Verified": -1} on failure
```

**2. Auto-submit if gate pipeline succeeded**

```python
if is_gate and succeeded:
    gerrit_conn.submit_change(change_id)
    # POST /a/changes/{change}/submit
```

**3. Remove from pipeline queue**

```python
redis.queue_remove(f"torri:pipeline:{pipeline_name}:queue", change_id)
```

**4. Refresh UI status snapshot**

```python
refresh_status(redis, list(pipeline_configs.keys()))
```

---

## Stage 10 — Status Snapshot

**File:** `microservices/Torri/src/torri/scheduler/status_writer.py`  
**Function:** `refresh_status(redis, pipeline_names)`

Called after every enqueue and after every pipeline completion.

**Process for each pipeline:**
1. Read all change IDs from `torri:pipeline:{pipeline_name}:queue`.
2. For each change ID, load the cached `GerritChange` from Redis.
3. Scan for job keys matching `torri:job:{pipeline_name}:{change_id}:*`.
4. Assemble a snapshot dict.

**Writes to:**
```
Key:   torri:ui:status
Value: JSON (no TTL)
```

**Shape:**
```json
{
  "last_updated": "2026-05-16T14:32:45.123456+00:00",
  "pipelines": [
    {
      "name": "check",
      "changes": [
        {
          "id": "123",
          "project": "libraries/common-utils",
          "branch": "main",
          "subject": "Fix memory leak in parser",
          "patchset": "2",
          "author": "John Doe",
          "url": "http://gerrit:8080/c/libraries/common-utils/+/123",
          "jobs": [
            {
              "job_id": "check:123:unit-tests:abc123",
              "job_name": "unit-tests",
              "status": "success",
              "start_time": "2026-05-16T14:32:00+00:00",
              "end_time": "2026-05-16T14:32:50+00:00",
              "url": null
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Stage 11 — Status API Serves the Dashboard

**File:** `microservices/Torri/status_api/server.py`

A FastAPI app running on port 8000 inside the scheduler container. nginx proxies `/api` to it.

```
GET /api/status
```

Reads `torri:ui:status` from Redis, returns it as JSON. If the key is missing, returns an empty pipelines list.

The React dashboard (`web/src/hooks/useStatusPolling.ts`) polls this endpoint on a fixed interval and renders the result via `web/src/components/Dashboard.tsx`.

---

## Redis Keys Reference

| Key | Type | Content | TTL |
|---|---|---|---|
| `torri:change:{number}` | string (pickle) | Latest `GerritChange` | 7 days |
| `torri:change:{number}:{patchset}` | string (pickle) | Versioned `GerritChange` | 7 days |
| `torri:pipeline:{name}:queue` | list | Change IDs in queue | none |
| `torri:started:{pipeline}:{change}:{patchset}` | string | Duplicate-guard sentinel | none |
| `torri:job:{pipeline}:{change}:{job_name}` | string (JSON) | Job state dict | none |
| `torri:ui:status` | string (JSON) | Full status snapshot | none |

---

## Threads Summary

| Thread | Class / Function | Blocks on |
|---|---|---|
| Kafka consumer | `KafkaConnection.get_events()` | `confluent_kafka.Consumer.poll()` |
| Event processor | `GerritEventProcessor.run()` | `kafka_connection.getEvent()` |
| Trigger bridge | `_trigger_bridge()` | `trigger_kafka.getEvent()` |
| Scheduler loop | `SchedulerQueue.run()` | `event_queue.get(timeout=1)` |
| Merge worker | `_merge_worker()` | Kafka `merger-responses` poll |
| Job worker (×N) | `_run_job()` | `time.sleep()` (mock) |
| Status API | uvicorn (FastAPI) | incoming HTTP requests |
