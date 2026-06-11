"""
Status snapshot writer.

Reads pipeline queues and buildset states from Redis and writes a single
JSON blob under torri:ui:status that the web API server can serve.

Called by the scheduler after every change enqueue and every job completion.
Multiple scheduler instances all write to the same key, so the last writer wins —
which is fine because the content is derived from the same Redis source of truth.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List

import logging

from torri.scheduler.redis_client import TorriRedis

STATUS_KEY = "torri:ui:status"
BUILDSET_LOOKUP_PREFIX = "torri:change:buildset:"
BUILDSET_KEY_PREFIX = "torri:buildset:"

logger = logging.getLogger("torri.scheduler.status_writer")


def refresh_status(
    redis: TorriRedis,
    pipeline_names: List[str],
):
    """
    Rebuild the full status snapshot and write it to Redis.

    For each pipeline, read its queue, fetch each change's details from
    the Redis pickle cache (stored during enrichment), and collect job states.
    """
    try:
        pipelines = []
        for pipeline_name in pipeline_names:
            changes = _build_pipeline_changes(redis, pipeline_name)
            pipelines.append({"name": pipeline_name, "changes": changes})

        snapshot = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "pipelines": pipelines,
        }
        redis.set_state(STATUS_KEY, snapshot)
        logger.debug("Status snapshot refreshed, %d pipelines", len(pipelines))

    except Exception as e:
        logger.error("Failed to refresh status snapshot: %s", e, exc_info=True)


def _build_pipeline_changes(redis: TorriRedis, pipeline_name: str) -> List[dict]:
    queue_key = f"torri:pipeline:{pipeline_name}:queue"
    change_ids = redis.queue_list_all(queue_key)

    changes = []
    for change_id in change_ids:
        change_dict = _build_change(redis, pipeline_name, change_id)
        if change_dict:
            changes.append(change_dict)
    return changes


def _build_change(redis: TorriRedis, pipeline_name: str, change_id: str) -> dict:
    cached_change = redis.get_change(change_id)

    subject = ""
    branch = ""
    project = ""
    author = ""
    patchset = ""
    url = ""

    if cached_change:
        subject = cached_change.subject
        branch = cached_change.branch
        project = cached_change.project
        author = cached_change.author
        patchset = str(cached_change.patchset)
        url = cached_change.url

    buildset_uuid, jobs = _collect_jobs(redis, pipeline_name, change_id, patchset)

    return {
        "id": change_id,
        "project": project or change_id,
        "branch": branch,
        "subject": subject or f"Change {change_id}",
        "patchset": patchset,
        "author": author,
        "url": url,
        "buildset_uuid": buildset_uuid,
        "jobs": jobs,
    }


def _collect_jobs(redis: TorriRedis, pipeline_name: str, change_id: str, patchset: str) -> tuple:
    """
    Look up the buildset for this change+patchset+pipeline and return its jobs.

    Returns (buildset_uuid, jobs_list).
    """
    if patchset:
        lookup_key = f"{BUILDSET_LOOKUP_PREFIX}{change_id}:{patchset}:{pipeline_name}"
        buildset_uuid = redis.client.get(lookup_key)
    else:
        buildset_uuid = None

    if not buildset_uuid:
        return "", []

    buildset_data = redis.get_state(f"{BUILDSET_KEY_PREFIX}{buildset_uuid}")
    if not buildset_data:
        return buildset_uuid, []

    jobs = [
        {
            "job_uuid": j.get("job_uuid", ""),
            "job_name": j.get("job_name", ""),
            "status": j.get("status", "queued"),
            "start_time": j.get("start_time"),
            "end_time": j.get("end_time"),
            "duration_seconds": j.get("duration_seconds"),
            "log_url": j.get("log_url", ""),
        }
        for j in buildset_data.get("jobs", [])
    ]
    return buildset_uuid, jobs
