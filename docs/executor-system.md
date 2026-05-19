# Executor System

This document describes the job execution system built on top of the Torii scheduler.

---

## Overview

When a change passes pipeline requirements and the merger produces a synthetic ref, the scheduler no longer runs mock threads. Instead it publishes jobs to Kafka and a dedicated executor process runs them in isolated sandboxes.

```
Scheduler
  → executor_dispatcher.dispatch()
      → writes Buildset to Redis
      → publishes N messages to job-requests (one per job)

Executor (separate container)
  → reads job-requests
  → spawns JobWorker thread per job
      → clones project from merger at synthetic ref
      → acquires runner (Docker container or SSH VM)
      → runs pre-run / run / post-run Ansible playbooks
          (each playbook subprocess wrapped in bwrap sandbox)
      → streams log lines to Redis List
      → publishes result to job-results

Scheduler (ResultConsumer thread)
  → reads job-results
  → calls on_done() when all jobs in a buildset finish

Browser
  → polls /api/status (change + job status)
  → clicks a job badge → opens LogPanel (WebSocket /ws/job/{uuid}/logs)
      → xterm.js terminal streams live log output
```

---

## Files Changed or Created

### YAML Configuration

| File | Change |
|------|--------|
| `compose/files/torri/nodesets.yaml` | New — defines `single-python` and `single-debian` nodesets |
| `compose/files/torri/jobs.yaml` | Updated — all jobs now have `nodeset`, `timeout`, `run` (and optional `pre-run`, `post-run`) |
| `microservices/Torri/src/torri/config/layout/nodesets.yaml` | New — same content, runtime copy |
| `microservices/Torri/src/torri/config/layout/jobs.yaml` | Updated — same content, runtime copy |
| `microservices/Torri/src/torri/config/torii.conf` | Added `merger.base_url`, `job-requests`/`job-results` topics, fixed Kafka host to `kafka:9094` |

**jobs.yaml fields per job:**
```yaml
- job:
    name: unit-tests
    nodeset: single-python   # which nodeset to allocate
    timeout: 600             # seconds before the job is killed
    pre-run: playbooks/unit-tests/pre.yaml   # optional
    run: playbooks/unit-tests/run.yaml       # required
    post-run: playbooks/unit-tests/post.yaml # optional, runs even on failure
```

**nodesets.yaml:**
```yaml
nodesets:
  - nodeset:
      name: single-python
      nodes:
        - name: builder
          label: python-slim   # maps to Docker image or SSH VM label
```

---

### Validator (`microservices/Shared/src/shared/layout_validator.py`)

- `createNodesetsSchema()` — validates `nodesets.yaml`
- `createJobsSchema(nodeset_names)` — now validates `nodeset`, `timeout`, `pre-run`, `run`, `post-run`
- `validate()` — accepts `list_of_nodesets` parameter
- `validateAllFiles()` — validation order is now: nodesets → jobs → pipelines → projects

---

### Scheduler (`microservices/Torri/src/torri/scheduler/`)

#### `buildset.py` (new)
Dataclasses representing one pipeline run for a change:
- `JobInBuildset` — `job_uuid`, `job_name`, `status`
- `Buildset` — groups all jobs, tracks overall `status` (running / succeeded / failed)

#### `executor_dispatcher.py` (new, replaces `launch_jobs`)
- `dispatch()` — creates a Buildset, writes it to Redis, publishes one Kafka message per job to `job-requests`
- `on_job_result()` — called by ResultConsumer; updates job status in Redis and fires `on_done` when all jobs finish
- Redis keys written:
  - `torri:buildset:{buildset_uuid}` — full buildset JSON (7-day TTL)
  - `torri:change:buildset:{change_id}:{patchset}:{pipeline}` — lookup key (7-day TTL)

#### `result_consumer.py` (new)
Background thread started by `cmd/scheduler.py`:
- Kafka consumer on `job-results` topic (group `scheduler-result-consumer`)
- Calls `executor_dispatcher.on_job_result()` per message
- Triggers `refresh_status()` after each result

#### `scheduler_queue.py` (updated)
- Accepts `kafka_bootstrap` and `merger_base_url` constructor params
- Loads `jobs.yaml` and `nodesets.yaml` at startup into `self.job_configs` and `self.nodeset_configs`
- `on_merge_done` closure now calls `executor_dispatcher.dispatch()` instead of `launch_jobs()`

#### `status_writer.py` (updated)
- Reads buildset UUID from `torri:change:buildset:*` lookup key
- Reads full buildset from `torri:buildset:{uuid}`
- Includes `buildset_uuid` and per-job `job_uuid` in the status snapshot

#### `cmd/scheduler.py` (updated)
- YAML validation now includes `nodesets.yaml`
- Passes `kafka_bootstrap` and `merger_base_url` to `SchedulerQueue`
- Starts `ResultConsumer` thread after the scheduler is running

---

### Executor Microservice (`microservices/Executor/`)

New Python package with entry point `torri-executor`.

```
microservices/Executor/
  pyproject.toml
  src/executor/
    executor.conf         # INI config (Kafka, Redis, bwrap toggle, image labels)
    config.py             # Config reader
    cmd/
      executor.py         # Entry point: Kafka consumer + semaphore-limited workers
    job_worker.py         # Full job lifecycle
    ansible_runner.py     # Runs ansible-playbook (optionally inside bwrap)
    log_relay.py          # Writes log lines to Redis List
    node_pool.py          # Redis-backed VM claim/release
    runners/
      base.py             # Abstract interface
      docker_runner.py    # Ephemeral Docker containers
      ssh_runner.py       # SSH VMs from node pool
```

#### `cmd/executor.py`
- Kafka consumer on `job-requests` (group `executor-group`)
- `threading.Semaphore(max_workers)` limits concurrent jobs
- Spawns one `JobWorker` thread per job

#### `job_worker.py`
Full lifecycle per job:
1. Create `/var/torii/jobs/{job_uuid}/src/`, `playbooks/`, `ansible/`
2. `git clone {merger_base_url}/{project}` then `git checkout` the synthetic ref
3. Acquire a runner (Docker or SSH)
4. Write `ansible/inventory` and `ansible/ansible.cfg`
5. Run `pre-run`, `run`, `post-run` playbooks via `ansible_runner.run_playbook()`
6. Release the runner, delete the job directory
7. Publish `{job_uuid, buildset_uuid, status}` to `job-results`

#### `ansible_runner.py`
- Runs `ansible-playbook` as a subprocess
- When `use_bwrap=True` wraps the subprocess in `bwrap`:
  - `/usr`, `/bin`, `/lib`, `/lib64` — read-only bind mounts
  - `/proc`, `/dev`, `/tmp` — standard pseudo-filesystems
  - `/etc/resolv.conf`, `/etc/ssl/certs` — read-only (DNS/TLS for Ansible)
  - `{job_dir}` — the only writable path
  - `--unshare-pid` — private PID namespace (cannot signal other jobs)
  - `--die-with-parent` — killed if the executor process dies
  - Network is NOT isolated (Ansible needs to reach target nodes)
- Falls back to direct execution if `bwrap` is not in PATH

#### `log_relay.py`
- `RPUSH torri:log:{job_uuid} {line}` — appends each line
- `LTRIM` to last 5000 lines
- 7-day TTL
- Writes `__EOF__` sentinel when the job finishes

#### `node_pool.py`
- Loads `nodes.yaml` at startup, registers each VM in Redis via `HSET`
- `claim(label, job_uuid)` — `SETNX torri:node:lock:{hostname} {job_uuid}` with 2-hour safety TTL
- `release(hostname)` — `DEL torri:node:lock:{hostname}`

#### Runners

**DockerRunner**
- `acquire()` — `docker run -d --name torii-{job_uuid}-{node_name} {image} sleep infinity`
- `release()` — `docker rm -f {container_name}`
- Inventory: `ansible_connection=docker`

**SshRunner**
- `acquire()` — claims a VM from NodePool by label
- `release()` — returns VM to pool
- Inventory: `ansible_connection=ssh`
- `ansible.cfg` extras: `ControlMaster=auto ControlPersist=60s`, `pipelining=True`

#### Runner selection
The label in the nodeset node determines the runner:
- If the label maps to a Docker image in `[images]` → `DockerRunner`
- Otherwise look for the label in the SSH node pool → `SshRunner`

`executor.conf` `[images]` section:
```ini
[images]
python-slim = python:3.12-slim
debian-bookworm = debian:bookworm-slim
```

---

### Status API (`microservices/Torri/status_api/server.py`)

Two new endpoints added:

| Endpoint | Description |
|----------|-------------|
| `GET /api/buildset/{buildset_uuid}` | Full buildset detail (job statuses) |
| `WS /ws/job/{job_uuid}/logs` | Stream log lines; polls Redis List every 200ms, closes on `__EOF__` |

---

### nginx (`compose/files/nginx/nginx.conf`)

Added `/ws` location block to proxy WebSocket connections to the status API:
```nginx
location /ws {
    proxy_pass http://status_api;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
}
```

---

### Web UI (`web/`)

#### `package.json`
- Added `@xterm/xterm ^5.5.0` and `@xterm/addon-fit ^0.10.0`

#### `src/types/status.ts`
- `Job.job_uuid` (replaces `job_id`)
- `Job.status` extended: `timeout`, `cancelled`
- `Change.buildset_uuid` added

#### `src/components/Dashboard.tsx`
- Job badges are now `<button>` elements (not `<a>` links)
- Clicking a job badge (when status is not `queued`) opens the log panel
- `selectedJob` state tracks the currently viewed job
- Page bottom padding adjusts when the log panel is open

#### `src/components/LogPanel.tsx` (new)
- Fixed `position: fixed; bottom: 0` panel — DevTools style, 40vh height
- Title bar shows job name, close button dismisses the panel
- Mounts an xterm.js `Terminal` with dark theme
- Opens `WebSocket /ws/job/{job_uuid}/logs` on mount
- Writes each received line to the terminal; closes on `__EOF__` sentinel
- Cleans up terminal and WebSocket on unmount

---

## Redis Keys Summary

| Key | Written by | Read by | TTL |
|-----|-----------|---------|-----|
| `torri:buildset:{uuid}` | dispatcher, result_consumer | status_writer, status_api | 7 days |
| `torri:change:buildset:{cid}:{ps}:{pipeline}` | dispatcher | status_writer | 7 days |
| `torri:log:{job_uuid}` | executor log_relay | status_api WebSocket | 7 days |
| `torri:node:lock:{hostname}` | node_pool claim | node_pool release | 2 hours |
| `torri:nodepool:vm:{hostname}` | node_pool load | (informational) | none |

---

## What Needs to Happen Next

1. **Add executor to Docker Compose** — create a `Dockerfile` stage or service for the executor container, mount `executor.conf` and `nodes.yaml`.
2. **Create nodes.yaml** — list real SSH VMs if SSH runners are needed; leave empty if only Docker runners are used.
3. **Write job playbooks** — create `playbooks/{job-name}/run.yaml` in each project repository.
4. **Enable bwrap in executor container** — user namespaces must be enabled (`sysctl kernel.unprivileged_userns_clone=1`) or the container must run with `--security-opt seccomp=unconfined`.
5. **Install npm dependencies** — run `npm install` in `web/` to pull in `@xterm/xterm` and `@xterm/addon-fit`.
6. **Patchset collision fixes** — the reverted fixes (patchset in job key, cancellation of superseded patchset jobs) still need to be re-applied.
