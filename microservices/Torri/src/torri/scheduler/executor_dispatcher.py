"""
Executor dispatcher — the scheduler side of job execution.

When a change is ready to run (merger has produced a synthetic ref), the
scheduler calls dispatch() instead of the old launch_jobs().

dispatch() does three things:
  1. Creates a Buildset, writes it to Redis.
  2. Publishes one Kafka message per job to the job-requests topic.
     Each message is self-contained: the executor needs nothing else to run.
  3. Registers an on_done callback so result_consumer can fire it when
     all jobs in the buildset finish.

result_consumer calls on_job_result() as each job-results message arrives.
"""

import json
import logging
import threading
import uuid
import yaml
import os
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from torri.kafka.producer import KafkaProducerClient
from torri.scheduler.buildset import Buildset, JobInBuildset
from torri.scheduler.redis_client import TorriRedis

logger = logging.getLogger("torri.scheduler.executor_dispatcher")

JOB_REQUESTS_TOPIC = "job-requests"
BUILDSET_KEY_PREFIX = "torri:buildset:"
# maps change+patchset+pipeline → buildset_uuid for status_writer lookups
BUILDSET_LOOKUP_PREFIX = "torri:change:buildset:"
BUILDSET_TTL = 7 * 24 * 3600  # 7 days
TERMINAL_JOB_STATUSES = {"success", "failure", "timeout", "cancelled", "succeeded", "failed"}

# Maps buildset_uuid → in-flight tracking state.
# Accessed from multiple threads (dispatcher + result_consumer).
_pending: Dict[str, dict] = {}
_pending_lock = threading.Lock()


def dispatch(
    change_id: str,
    patchset: str,
    pipeline: str,
    project: str,
    branch: str,
    job_names: List[str],
    job_configs: Dict[str, dict],
    nodeset_configs: Dict[str, dict],
    synthetic_ref: str,
    kafka_bootstrap: str,
    redis: TorriRedis,
    on_done: Callable[[str, str], None],
    web_root_url: str = "",
) -> str:
    """
    Create a buildset and dispatch all jobs to the executor via Kafka.

    job_configs: job_name → {nodeset, timeout, pre_run, run, post_run}
    nodeset_configs: nodeset_name → {name, nodes: [{name, label}]}

    Returns the buildset_uuid.
    """
    if not job_names:
        on_done("succeeded", "")
        return ""

    buildset_uuid = uuid.uuid4().hex
    jobs = []
    for name in job_names:
        job_uuid = uuid.uuid4().hex
        jobs.append(
            JobInBuildset(
                job_uuid=job_uuid,
                job_name=name,
                log_url=_build_job_log_url(web_root_url, buildset_uuid, job_uuid),
            )
        )
    buildset = Buildset(
        buildset_uuid=buildset_uuid,
        change_id=change_id,
        patchset=patchset,
        pipeline=pipeline,
        project=project,
        branch=branch,
        jobs=jobs,
    )

    # Write buildset state so the UI can show it immediately.
    redis_key = f"{BUILDSET_KEY_PREFIX}{buildset_uuid}"
    redis.set_state(redis_key, buildset.to_dict())
    redis.client.expire(redis_key, BUILDSET_TTL)

    # Write lookup key so status_writer can find the buildset for a change.
    lookup_key = f"{BUILDSET_LOOKUP_PREFIX}{change_id}:{patchset}:{pipeline}"
    redis.client.set(lookup_key, buildset_uuid, ex=BUILDSET_TTL)

    with _pending_lock:
        _pending[buildset_uuid] = {
            "on_done": on_done,
            "total": len(jobs),
            "done": 0,
            "failed": False,
            "redis": redis,
            "buildset": buildset,
        }

    try:
        producer = KafkaProducerClient(kafka_bootstrap)
        for job in jobs:
            job_config = job_configs.get(job.job_name, {})
            nodeset_name = job_config.get("nodeset", "")
            nodeset_config = nodeset_configs.get(nodeset_name, {})

            payload = {
                "job_uuid": job.job_uuid,
                "buildset_uuid": buildset_uuid,
                "change_id": change_id,
                "patchset": patchset,
                "pipeline": pipeline,
                "project": project,
                "branch": branch,
                "job_name": job.job_name,
                "job_config": job_config,
                "nodeset_config": nodeset_config,
                "synthetic_ref": synthetic_ref,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
            }
            producer.send_message(
                JOB_REQUESTS_TOPIC,
                key=job.job_uuid,
                value=json.dumps(payload),
            )
            logger.info(
                "Dispatched job=%s buildset=%s change=%s pipeline=%s",
                job.job_name, buildset_uuid, change_id, pipeline,
            )

        producer.flush()

    except Exception as e:
        logger.error("Failed to dispatch jobs for buildset=%s: %s", buildset_uuid, e, exc_info=True)
        with _pending_lock:
            _pending.pop(buildset_uuid, None)
        on_done("failed", "")
        return buildset_uuid

    return buildset_uuid


def on_job_result(
    redis: TorriRedis,
    job_uuid: str,
    buildset_uuid: str,
    job_name: str,
    status: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> None:
    """
    Called by result_consumer when a single job finishes.

    Updates Redis buildset state and fires on_done when all jobs are done.
    """
    with _pending_lock:
        entry = _pending.get(buildset_uuid)
        
        if entry is None:
            logger.warning("Received result for disconnected buildset=%s job=%s, updating Redis fallback", buildset_uuid, job_uuid)
            redis_key = f"{BUILDSET_KEY_PREFIX}{buildset_uuid}"
            bs_dict = redis.get_state(redis_key)
            if not bs_dict:
                logger.error("Buildset %s not found in redis either!", buildset_uuid)
                return

            done_count = 0
            failed = False
            for j in bs_dict.get("jobs", []):
                if j.get("job_uuid") == job_uuid:
                    _apply_job_dict_result(j, status, start_time, end_time, duration_seconds)
                
                j_status = j.get("status")
                if j_status in TERMINAL_JOB_STATUSES:
                    done_count += 1
                if j_status in ("failure", "failed"):
                    failed = True
            
            all_done = done_count == len(bs_dict.get("jobs", []))
            if all_done:
                bs_dict["status"] = "failed" if failed else "succeeded"
                bs_dict["summary"] = _build_summary_from_dict(bs_dict)
                # If fully disconnected, at least remove it from the queue so the UI drops it
                pipeline = bs_dict.get("pipeline")
                change_id = bs_dict.get("change_id")
                redis.queue_remove(f"torri:pipeline:{pipeline}:queue", change_id)
                
            redis.set_state(redis_key, bs_dict)
            return

        buildset: Buildset = entry["buildset"]
        # "redis" argument was passed in, but we can assert or use the one from entry if we want.

        for job in buildset.jobs:
            if job.job_uuid == job_uuid:
                was_done = job.status in TERMINAL_JOB_STATUSES
                job.status = status
                if start_time:
                    job.start_time = start_time
                if end_time:
                    job.end_time = end_time
                if duration_seconds is not None:
                    job.duration_seconds = duration_seconds
                elif job.start_time and job.end_time:
                    job.duration_seconds = _calculate_duration_seconds(job.start_time, job.end_time)
                if status in TERMINAL_JOB_STATUSES and not was_done:
                    entry["done"] += 1
                break

        if status in ("failure", "failed"):
            entry["failed"] = True

        all_done = entry["done"] == entry["total"]

        if all_done:
            buildset.status = "failed" if entry["failed"] else "succeeded"
            buildset.summary = _build_summary(buildset)
            _pending.pop(buildset_uuid)

    # Update Redis with the latest buildset state.
    redis_key = f"{BUILDSET_KEY_PREFIX}{buildset_uuid}"
    redis.set_state(redis_key, buildset.to_dict())

    if all_done:
        entry["on_done"]("failed" if entry["failed"] else "succeeded", buildset.summary)


def _build_job_log_url(web_root_url: str, buildset_uuid: str, job_uuid: str) -> str:
    path = f"/buildsets?buildset={buildset_uuid}&job={job_uuid}"
    if not web_root_url:
        return path
    return f"{web_root_url.rstrip('/')}{path}"


def _apply_job_dict_result(
    job: dict,
    status: str,
    start_time: Optional[str],
    end_time: Optional[str],
    duration_seconds: Optional[float],
) -> None:
    job["status"] = status
    if start_time:
        job["start_time"] = start_time
    if end_time:
        job["end_time"] = end_time
    if duration_seconds is not None:
        job["duration_seconds"] = duration_seconds
    elif job.get("start_time") and job.get("end_time"):
        job["duration_seconds"] = _calculate_duration_seconds(job["start_time"], job["end_time"])


def _calculate_duration_seconds(start_time: str, end_time: str) -> Optional[float]:
    try:
        start = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        return round((end - start).total_seconds(), 3)
    except ValueError:
        return None


def _build_summary(buildset: Buildset) -> str:
    buildset_dict = buildset.to_dict()
    return _build_summary_from_dict(buildset_dict)


def _build_summary_from_dict(buildset: dict) -> str:
    status = _format_status(buildset.get("status", "finished"))
    lines = [
        f"[Torii] {buildset.get('pipeline', '')} build finished for change {buildset.get('change_id', '')}, patchset {buildset.get('patchset', '')}: {status}",
        "",
        "Jobs:",
    ]
    for job in buildset.get("jobs", []):
        duration = _format_duration(job.get("duration_seconds"))
        lines.append(
            f"- {job.get('job_name', '')}: {_format_status(job.get('status', 'unknown'))}, {duration}, logs: {job.get('log_url', '')}"
        )
    return "\n".join(lines)


def _format_status(status: str) -> str:
    labels = {
        "success": "Success",
        "succeeded": "Success",
        "failure": "Failed",
        "failed": "Failed",
        "running": "Running",
        "queued": "Queued",
        "timeout": "Timeout",
        "cancelled": "Cancelled",
    }
    return labels.get(status, status.capitalize())


def _format_duration(duration_seconds: Optional[float]) -> str:
    if duration_seconds is None:
        return "duration unavailable"
    if duration_seconds < 60:
        return f"{duration_seconds:.3f}s"
    minutes = int(duration_seconds // 60)
    seconds = duration_seconds % 60
    return f"{minutes}m {seconds:06.3f}s"
