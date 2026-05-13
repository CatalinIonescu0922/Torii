"""
Mock job runner.

When a change is enqueued in a pipeline, the scheduler calls launch_jobs().
Each job sleeps for JOB_DURATION_SECONDS, then writes 'success' to Redis and
triggers a status refresh so the web UI sees the final state.

This replaces real job execution until the actual job-launch layer is built.
"""

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import List, Callable

import logging

from torri.scheduler.redis_client import TorriRedis

JOB_DURATION_SECONDS = 50

logger = logging.getLogger("torri.scheduler.job_runner")


def launch_jobs(
    change_id: str,
    pipeline_name: str,
    job_names: List[str],
    redis: TorriRedis,
    on_done: Callable[[bool], None],
    synthetic_ref: str = None,
):
    """
    Spawn one mock thread per job.

    Each thread sleeps JOB_DURATION_SECONDS then marks itself succeeded.
    Redis is used only to persist job status for the status API — the mock
    jobs don't need it to run. Real jobs would read synthetic_ref from Redis
    to know which commit to check out.

    synthetic_ref is required. If absent, the scheduler has a bug — we refuse
    to start rather than run jobs against an unknown codebase state.
    """
    if not synthetic_ref:
        logger.error(
            "launch_jobs called without synthetic_ref for change=%s pipeline=%s — refusing to start jobs",
            change_id, pipeline_name,
        )
        on_done(False)
        return

    if not job_names:
        on_done(True)
        return

    remaining = {"count": len(job_names), "failed": False}
    lock = threading.Lock()

    for job_name in job_names:
        job_id = f"{pipeline_name}:{change_id}:{job_name}:{uuid.uuid4().hex[:6]}"
        _write_job(redis, job_id, change_id, pipeline_name, job_name, "running", None, synthetic_ref)
        logger.info("Job started job_id=%s change=%s pipeline=%s ref=%s", job_id, change_id, pipeline_name, synthetic_ref)

        t = threading.Thread(
            target=_run_job,
            args=(job_id, change_id, pipeline_name, job_name, redis, remaining, lock, on_done),
            daemon=True,
            name=f"job-{job_id}",
        )
        t.start()


def _run_job(job_id, change_id, pipeline_name, job_name, redis, remaining, lock, on_done):
    time.sleep(JOB_DURATION_SECONDS)
    end_time = datetime.now(timezone.utc).isoformat()
    _write_job(redis, job_id, change_id, pipeline_name, job_name, "success", end_time)
    logger.info("Job finished job_id=%s change=%s pipeline=%s", job_id, change_id, pipeline_name)

    with lock:
        remaining["count"] -= 1
        all_done = remaining["count"] == 0
        succeeded = not remaining["failed"]

    if all_done:
        on_done(succeeded)


def _write_job(redis, job_id, change_id, pipeline_name, job_name, status, end_time, synthetic_ref=None):
    key = f"torri:job:{pipeline_name}:{change_id}:{job_name}"
    now = datetime.now(timezone.utc).isoformat()
    redis.set_state(key, {
        "job_id": job_id,
        "job_name": job_name,
        "change_id": change_id,
        "pipeline_name": pipeline_name,
        "status": status,
        "start_time": now if status == "running" else None,
        "end_time": end_time,
        "synthetic_ref": synthetic_ref,
    })
