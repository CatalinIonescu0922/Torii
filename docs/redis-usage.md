# Redis Usage in Torii

Redis serves four distinct roles in this system: change caching, pipeline queuing,
idempotency guards, and live UI state. This document covers every key, command,
data format, TTL, and which file owns each operation.

---

## Connection

**File:** `microservices/Torri/src/torri/scheduler/redis_client.py`

`TorriRedis` wraps `redis.from_url()` and exposes two clients from the same
connection pool:

| Client | `decode_responses` | Used for |
|---|---|---|
| `self.client` | `True` (text) | All JSON and string operations |
| `self._binary_client` | `False` (binary) | Pickle-serialized `GerritChange` objects |

URL comes from `torii.conf` → `config.redis_url` → passed down to every component
at startup. Default: `redis://redis:6379/0`.

---

## All Redis Keys at a Glance

| Key pattern | Type | TTL | Owned by |
|---|---|---|---|
| `torri:change:{number}` | String (pickle) | 7 days | `redis_client.py` |
| `torri:change:{number}:{patchset}` | String (pickle) | 7 days | `redis_client.py` |
| `torri:rejected:{pipeline}:{change}:{patch}` | String | 24 h | `scheduler_queue.py` |
| `torri:started:{pipeline}:{change}:{patch}` | String | 24 h | `scheduler_queue.py` |
| `torri:pipeline:{pipeline}:queue` | List | none | `pipeline_manager.py` |   
| `torri:pipeline:{pipeline}:window` | String (JSON) | none | `pipeline_manager.py` |
| `torri:change:{change}:state` | String (JSON) | none | `pipeline_manager.py` |
| `torri:buildset:{buildset}:state` | String (JSON) | none | `pipeline_manager.py` |
| `torri:job:{pipeline}:{change}:{patchset}:{job}` | String (JSON) | none | `job_runner.py` |
| `torri:ui:status` | String (JSON) | none | `status_writer.py` |

---

## Use Case 1 — Change Caching (GerritChange objects)

**Keys:**
```
torri:change:{change_number}
torri:change:{change_number}:{patchset}
```

**Commands:** `SETEX` (write), `GET` (read)  
**Format:** Binary pickle of a `GerritChange` object  
**TTL:** 7 days

**Why two keys?**
The first key always points to the latest patchset and gets overwritten on every
update. The second key is versioned and never overwritten — the scheduler can fetch
exactly the state it saw at a specific patchset without the latest overwriting it.

**Written by:** `GerritRestConnection._updateChange()` after every Gerrit REST fetch.

**Read by:**
- `GerritRestConnection._getChange()` — checked before hitting the REST API. Skipped when `refresh=True` (every live event forces a fresh fetch).
- `status_writer.refresh_status()` — reads the cached object to populate the UI status snapshot with project, branch, subject, and author without an extra REST call.

**What a `GerritChange` contains:**
```
number, patchset, project, branch, status (NEW/MERGED/ABANDONED),
subject, author, url, labels {Code-Review: 2, Verified: 1, ...},
needs_changes (dependencies), needed_by_changes
```

---

## Use Case 2 — Idempotency Guards (SETNX)

Two separate guards live in `scheduler_queue.py`. Both use `SETNX` (set-if-not-exists),
which is atomic — only one thread/instance can win.

### 2a — Rejection guard

**Key:** `torri:rejected:{pipeline_name}:{change_id}:{patch_number}`  
**Value:** Rejection reason string, e.g. `"Missing required vote: Code-Review is +1, need +2"`  
**TTL:** 24 hours  
**Commands:** `SETNX`, `EXPIRE`

**Purpose:** If a change fails requirements, Gerrit gets one rejection comment per
patchset per pipeline. Without this guard, every Kafka replay of the same event
would post a duplicate comment. The `SETNX` means only the first failure comment
is sent; the key's presence is checked again on the next event, but a later event
that now *passes* requirements goes right through to the start guard below — the
rejection key does not block admission.

**Known gap:** If the rejection reason changes between events (e.g. Code-Review +2
is added but Verified is still missing), the developer does not see the updated
reason on Gerrit. The key only stores the first reason.

### 2b — Start guard

**Key:** `torri:started:{pipeline_name}:{change_id}:{patch_number}`  
**Value:** Literal `"1"`  
**TTL:** 24 hours  
**Commands:** `SETNX`, `EXPIRE`

**Purpose:** Ensures a change enters a pipeline exactly once per patchset per pipeline,
even if Kafka delivers the triggering event multiple times (container restart, consumer
group rebalance, offset reset).

The patchset number is part of the key so patchset 3 always gets a fresh key,
independent of whether patchset 2 ran before it.

```python
start_key = f"torri:started:{pipeline_name}:{change_id}:{event.patch_number}"
already_started = not self.redis.client.setnx(start_key, "1")
```

---

## Use Case 3 — Pipeline Queues

**Key:** `torri:pipeline:{pipeline_name}:queue`  
**Type:** Redis List (FIFO)  
**TTL:** none  
**Commands:** `RPUSH`, `LPOP`, `LLEN`, `LRANGE`, `LPOS`, `LREM`

**Owned by:** `pipeline_manager.py` — `BasePipelineManager` and its subclasses.

**Operations:**

| Operation | Command | Called when |
|---|---|---|
| Enqueue change | `RPUSH` | Change passes all requirements and the start guard |
| Check for duplicate in queue | `LPOS` | Before every `RPUSH`, prevents a change queuing twice |
| Dequeue next change | `LPOP` | Pipeline manager picks next work item |
| Get current length | `LLEN` | Window/concurrency checks |
| List all items | `LRANGE 0 -1` | `status_writer` reads the full queue to build the UI snapshot |
| Remove specific change | `LREM 0 value` | `on_done` callback removes the change after all its jobs finish |

**`on_done` remove is patchset-aware:** before removing, the scheduler checks
whether the current patchset in Redis still matches the patchset that started this
run. If a newer patchset has arrived and its run is now the authoritative one, the
old patchset's `on_done` skips the remove to avoid evicting the new run.

---

## Use Case 4 — Pipeline Window State

**Key:** `torri:pipeline:{pipeline_name}:window`  
**Type:** String (JSON)  
**TTL:** none  
**Commands:** `SET`, `GET`

```json
{"size": 5, "active": 2, "updated_at": "2026-05-17T12:00:00Z"}
```

**Purpose:** Controls maximum concurrency inside a pipeline. `size` is the configured
limit; `active` is the live count. The `DependentPipeline` (gate) uses this to decide
whether to pull the next change off the queue or wait.

---

## Use Case 5 — Change State

**Key:** `torri:change:{change_id}:state`  
**Type:** String (JSON)  
**TTL:** none  
**Commands:** `SET`, `GET`

```json
{
  "change_id": "123",
  "project_name": "libraries/common-utils",
  "branch": "main",
  "state": "queued",
  "buildsets": ["uuid1"],
  "queue_position": 1,
  "created_at": "2026-05-17T12:00:00Z"
}
```

**Purpose:** Tracks the lifecycle state of a change as it moves through the pipeline
(`NEW → QUEUED → PROCESSING → COMPLETED / FAILED`).

**Owned by:** `pipeline_manager.py` (`save_change_state` / `get_change_state`).

---

## Use Case 6 — Buildset State

**Key:** `torri:buildset:{buildset_id}:state`  
**Type:** String (JSON)  
**TTL:** none  
**Commands:** `SET`, `GET`

```json
{
  "buildset_id": "550e8400-e29b-41d4-a716-446655440000",
  "change_id": "123",
  "pipeline_id": "check",
  "attempt": 1,
  "status": "running",
  "jobs": {},
  "started_at": "2026-05-17T12:00:00Z",
  "ended_at": null
}
```

**Purpose:** Records a single build attempt for a change. A change can have multiple
buildsets if it is retried. Not yet wired into live job tracking — reserved for
when real job execution is implemented.

**Owned by:** `pipeline_manager.py`.

---

## Use Case 7 — Job State

**Key:** `torri:job:{pipeline_name}:{change_id}:{patchset}:{job_name}`  
**Type:** String (JSON)  
**TTL:** none  
**Commands:** `SET`, `GET`

```json
{
  "job_id": "check:123:unit-tests:a1b2c3",
  "job_name": "unit-tests",
  "change_id": "123",
  "pipeline_name": "check",
  "status": "running",
  "start_time": "2026-05-17T12:00:00Z",
  "end_time": null,
  "synthetic_ref": "refs/changes/23/123/1"
}
```

**Status values:** `running`, `success`, `failure`, `cancelled`

**Patchset is part of the key** to prevent collision between two patchsets of the
same change running concurrently. Both `torri:job:check:123:2:unit-tests` and
`torri:job:check:123:3:unit-tests` can coexist.

**Written by:** `job_runner._write_job()` — once when the job starts (`running`) and
once when it finishes (`success` / `failure` / `cancelled`).

**Read by:** `status_writer._collect_jobs()` via `SCAN_ITER torri:job:{pipeline}:{change}:*`
— the wildcard catches all patchsets and all job names for a given change+pipeline.

---

## Use Case 8 — UI Status Snapshot

**Key:** `torri:ui:status`  
**Type:** String (JSON)  
**TTL:** none  
**Commands:** `SET`, `GET`

**Written by:** `status_writer.refresh_status()` — called after every pipeline enqueue
and after every job completion. It reads the pipeline queues and job keys from Redis,
merges them with cached `GerritChange` details, and writes the full assembled blob.

**Read by:** `status_api/server.py` `GET /api/status` — returns the raw JSON directly
to the React dashboard.

**Shape:**
```json
{
  "last_updated": "2026-05-17T14:32:45Z",
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
          "author": "Jane Smith",
          "url": "http://gerrit:8080/c/libraries/common-utils/+/123",
          "jobs": [
            {
              "job_id": "check:123:unit-tests:abc123",
              "job_name": "unit-tests",
              "status": "success",
              "start_time": "2026-05-17T14:32:00Z",
              "end_time": "2026-05-17T14:32:50Z",
              "url": null
            }
          ]
        }
      ]
    }
  ]
}
```

The snapshot is a denormalized read-optimized view. The API server never scans Redis
itself — it only does a single `GET torri:ui:status`.

---

## Data Flow Through Redis

```
Gerrit REST response
  └─► redis.store_change()
        torri:change:{number}          (pickle, 7 days)
        torri:change:{number}:{patch}  (pickle, 7 days)

Scheduler receives trigger event
  ├─► redis.get_change()                    read cache for requirement check
  ├─► SETNX torri:rejected:...              one rejection comment to Gerrit
  ├─► SETNX torri:started:...              one pipeline entry per patchset
  ├─► queue_enqueue → torri:pipeline:...:queue   (List)
  ├─► set_state → torri:change:...:state         (JSON)
  └─► refresh_status()
        reads  torri:pipeline:...:queue
        reads  torri:change:{id} (pickle)
        reads  torri:job:...:*
        writes torri:ui:status (JSON)

Job thread (job_runner)
  ├─► _write_job("running") → torri:job:{pipeline}:{change}:{patch}:{job}
  └─► _write_job("success"/"cancelled") → same key
        └─► on_done() → refresh_status() → torri:ui:status updated

Status API (FastAPI)
  └─► GET torri:ui:status → JSON → React dashboard
```

---

## Redis Commands Reference

| Command | Used for |
|---|---|
| `SETEX` | Store pickle-serialized `GerritChange` with 7-day TTL |
| `GET` | Read any string key |
| `SET` | Store JSON state (no TTL) |
| `SETNX` | Atomic idempotency guards (rejected, started) |
| `EXPIRE` | Set 24h TTL on SETNX keys after they are created |
| `RPUSH` | Append change ID to pipeline queue |
| `LPOP` | Dequeue next change |
| `LLEN` | Queue depth check |
| `LRANGE 0 -1` | Read full queue for status snapshot |
| `LPOS` | Duplicate-in-queue check before RPUSH |
| `LREM 0 val` | Remove specific change ID from queue on completion |
| `SCAN_ITER pattern` | Find all job keys for a given change+pipeline |
| `DELETE` | Remove a key (cleanup utilities in `redis_client.py`) |
| `EXISTS` | Key existence check |
| `INCRBY` | Counter increment (available in `redis_client.py`, not yet used) |
| `PUBLISH` | Pub/Sub (available in `redis_client.py`, not yet used) |
