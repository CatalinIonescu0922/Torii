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
    on_done: Callable[[str], None],
) -> str:
    """
    Create a buildset and dispatch all jobs to the executor via Kafka.

    job_configs: job_name → {nodeset, timeout, pre_run, run, post_run}
    nodeset_configs: nodeset_name → {name, nodes: [{name, label}]}

    Returns the buildset_uuid.
    """
    if not job_names:
        on_done("succeeded")
        return ""

    buildset_uuid = uuid.uuid4().hex
    jobs = [JobInBuildset(job_uuid=uuid.uuid4().hex, job_name=name) for name in job_names]
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
        on_done("failed")
        return buildset_uuid

    return buildset_uuid


def on_job_result(job_uuid: str, buildset_uuid: str, job_name: str,status : str) -> None:
    """
    Called by result_consumer when a single job finishes.

    Updates Redis buildset state and fires on_done when all jobs are done.
    """
    with _pending_lock:
        entry = _pending.get(buildset_uuid)
        if entry is None:
            logger.warning("Received result for unknown buildset=%s job=%s", buildset_uuid, job_uuid)
            return

        buildset: Buildset = entry["buildset"]
        redis: TorriRedis = entry["redis"]

        for job in buildset.jobs:
            if job.job_uuid == job_uuid:
                job.status = status
                break

        if status == "failure":
            entry["failed"] = True
        if status == "failure" or status == "success":
            entry["done"] += 1

        all_done = entry["done"] == entry["total"]

        if all_done:
            buildset.status = "failed" if entry["failed"] else "succeeded"
            _pending.pop(buildset_uuid)

    # Update Redis with the latest buildset state.
    redis_key = f"{BUILDSET_KEY_PREFIX}{buildset_uuid}"
    redis.set_state(redis_key, buildset.to_dict())

    if all_done:
        entry["on_done"]("failed" if entry["failed"] else "succeeded")
