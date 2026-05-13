# Torii - Project Knowledge Base

Torii is a CI/CD scheduler that mimics what Zuul does: it listens to Gerrit events, validates changes against pipeline rules, and orchestrates speculative merges and job execution.

---

## Coding Guidelines

- Keep it simple. If you can't explain it to a 7 year old, it is too complex.
- No emojis.
- Variable names must be readable and meaningful.
- Comment only when the why is not obvious. Never comment the what.
- Don't over-engineer. Prefer fewer, clearer abstractions over many small ones.

---

## How the System Works (Event Flow)

```
Gerrit → Kafka plugin → topic: gerrit-stream-events
                                   ↓
                           KafkaConnection (kafka_client.py)
                           polls kafka, puts raw JSON in event_queue
                                   ↓
                           GerritEventProcessor (gerritconnection.py)
                           reads raw event, builds GerritTriggerEvent,
                           enriches with Gerrit REST API (getChange),
                           dispatches to sched.addEvent(event)
                                   ↓
                           SchedulerQueue (scheduler_queue.py)
                           reads events, checks approvals,
                           routes change into matching pipelines
                                   ↓
                           Redis stores change state and pipeline queues
```

---

## Key Files

| File | Purpose |
|------|---------|
| `microservices/Torri/src/torri/kafka/kafka_client.py` | Reads raw Kafka messages, exposes `event_queue` |
| `microservices/Torri/src/torri/gerrit/gerritconnection.py` | `GerritEventProcessor` enriches events; `GerritRestConnection` queries Gerrit REST |
| `microservices/Torri/src/torri/scheduler/scheduler_queue.py` | Main scheduler loop; routes events to pipelines |
| `microservices/Torri/src/torri/scheduler/pipeline_config.py` | `PipelineConfigLoader` / `PipelineConfig` — parses the actual pipelines.yaml format |
| `microservices/Torri/src/torri/scheduler/config_loader.py` | `ConfigurationLoader` — BROKEN (see issues below) |
| `microservices/Torri/src/torri/config/config_manager.py` | Reads `torii.conf` (INI format) |
| `microservices/Torri/src/torri/config/torii.conf` | Main INI config (paths, redis, gerrit, kafka) |
| `microservices/Torri/src/torri/cmd/scheduler.py` | Entry point for `torri-scheduler` — BROKEN (see issues) |
| `microservices/Shared/src/shared/layout_validator.py` | Voluptuous-based YAML validator — not yet wired into scheduler |
| `compose/files/torri/pipelines.yaml` | Pipeline definitions (baked into image) |
| `compose/files/torri/projects.yaml` | Project definitions (baked into image) |
| `compose/files/torri/jobs.yaml` | Job definitions (baked into image) |
| `compose/Dockerfile` | Multi-stage: builder → runtime-base → merger / scheduler |
| `compose/files/supervisor/scheduler/supervisord.conf` | Runs `torri-scheduler -d` |

---

## YAML File Format (actual format used)

### pipelines.yaml
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

### projects.yaml
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
      gate:
        jobs:
          - unit-tests
          - integration-tests
```

### jobs.yaml
```yaml
jobs:
  - job:
      name: unit-tests
```

`PipelineConfigLoader` (pipeline_config.py) parses this format correctly.
`ConfigurationLoader` (config_loader.py) does NOT — it expects `{name: data}` dict format.

## Known Issues (as of May 2026)

### FIXED

**1. `cmd/scheduler.py` now has a real `main()`**
Wires `KafkaConnection`, `GerritRestConnection`, `GerritEventProcessor`, `SchedulerQueue`,
sets `gerrit_conn.sched = scheduler_queue`, and blocks.

**2. `GerritRestConnection` constructor was called with wrong kwargs**
Fixed in `main()` — now called as `GerritRestConnection(base_url, auth=(user, password))`.
Note: `base_url` must NOT have a trailing `/a` — `_build_url` adds that for authenticated requests.

**3. `gerrit_connection.sched` was never set**
Fixed — `main()` sets `gerrit_conn.sched = scheduler_queue` before starting the processor.

**4. `SchedulerQueue._process_event` used `event.change` (no such attribute)**
Fixed — now uses `event.change_number`, `event.project_name`, `event.branch` directly.

**5. `SchedulerQueue.addEvent` used `event.change.number`**
Fixed — now uses `event.change_number`.

**6. `ConfigurationLoader` parsed YAML with wrong dict assumptions**
Fixed — `SchedulerQueue` no longer uses `ConfigurationLoader`. `_initialize_pipelines` uses
`PipelineConfigLoader` (which handles the real list format) and parses projects.yaml directly.

**7. `SchedulerQueue._process_event` had `NameError` on `pipeline` outside the loop**
Fixed — `pipeline.save_change_state()` is now inside the loop, called per pipeline.

**8. Dockerfile missing COPY for YAML files in scheduler stage**
Fixed — added `COPY compose/files/torri/ /app/Torri/src/torri/config/layout/` to scheduler stage.

**9. `torii.conf` had wrong `config_dir` path**
Fixed — changed to `config_dir=layout`. In `main()`, this is resolved relative to `torii.conf`
location, giving `/app/Torri/src/torri/config/layout` in the container.

**10. `torii.conf` had wrong Gerrit server and Redis host**
Fixed — `server=gerrit`, `user=torii`, `password=19D9aIn7zePb`, `redis_host=redis` (compose hostnames).

---

### STILL OPEN

**Label approval checking not implemented**
`GerritChange` does not store label votes (Code-Review, Verified etc.) from the REST response.
`_change_meets_requirements` only checks `require_open` and `require_current_patchset`.
The pipelines.yaml requires `code-review: 2` and `verified: 1` which are silently skipped.
To fix: add label parsing to `GerritChange.update()` and implement the check in `_change_meets_requirements`.

**`scheduler.py` and `scheduler_init.py` are dead code**
The two elaborate initialization files in `scheduler/` are not connected to anything.
They can be deleted or ignored.

**11. Mock job runner and status API added (May 2026)**
`scheduler/job_runner.py` — when a change is enqueued, `launch_jobs()` spawns one thread per job.
Each sleeps 50 seconds then marks status `success` in Redis (key: `torri:job:{pipeline}:{change}:{job_name}`).
After all jobs finish, calls `on_all_done` which triggers a status snapshot refresh.

`scheduler/status_writer.py` — `refresh_status()` reads pipeline queues and job keys from Redis,
fetches change details from the Gerrit connection cache, and writes a single JSON blob to
`torri:ui:status`. Called after every enqueue and after all jobs complete.

`status_api/server.py` — Tiny FastAPI app (port 8000) that reads `torri:ui:status` from Redis
and serves it as `GET /api/status` — the exact shape the React dashboard polls.
Runs as a second supervisor program inside the scheduler container.

nginx `/api` block now proxies to `torii_scheduler:8000`.

---

## What Needs to Happen Next

1. Implement actual job execution — replace the 50-second mock in `job_runner.py` with real Jenkins/job-system calls.
