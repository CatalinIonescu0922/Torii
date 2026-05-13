"""
Status snapshot writer.

Reads pipeline queues and job states from Redis and writes a single
JSON blob under torri:ui:status that the web API server can serve.

Called by the scheduler after every change enqueue and every job completion.
Multiple scheduler instances all write to the same key, so the last writer wins —
which is fine because the content is derived from the same Redis source of truth.
"""

import json
from datetime import datetime, timezone
from typing import Dict, List

from shared.logger_setup import get_logger
from torri.scheduler.redis_client import TorriRedis

STATUS_KEY = "torri:ui:status"

logger = get_logger("torri.scheduler.status_writer")


def refresh_status(
    redis: TorriRedis,
    pipeline_names: List[str],
    gerrit_conn,
):
    """
    Rebuild the full status snapshot and write it to Redis.

    For each pipeline, read its queue, then fetch each change's details
    (from the Gerrit change cache) and job states.
    """
    try:
        pipelines = []
        for pipeline_name in pipeline_names:
            changes = _build_pipeline_changes(redis, pipeline_name, gerrit_conn)
            pipelines.append({"name": pipeline_name, "changes": changes})

        snapshot = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "pipelines": pipelines,
        }
        redis.set_state(STATUS_KEY, snapshot)
        logger.debug("Status snapshot refreshed, %d pipelines", len(pipelines))

    except Exception as e:
        logger.error("Failed to refresh status snapshot: %s", e, exc_info=True)


def _build_pipeline_changes(redis: TorriRedis, pipeline_name: str, gerrit_conn) -> List[dict]:
    queue_key = f"torri:pipeline:{pipeline_name}:queue"
    change_ids = redis.queue_list_all(queue_key)

    changes = []
    for change_id in change_ids:
        change_dict = _build_change(redis, pipeline_name, change_id, gerrit_conn)
        if change_dict:
            changes.append(change_dict)
    return changes


def _build_change(redis: TorriRedis, pipeline_name: str, change_id: str, gerrit_conn) -> dict:
    # Pull the enriched change object from the Gerrit connection cache if available
    cached_change = None
    try:
        cached_change = gerrit_conn.getChange(change_id)
    except Exception:
        pass

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

    jobs = _collect_jobs(redis, pipeline_name, change_id)

    return {
        "id": change_id,
        "project": project or change_id,
        "branch": branch,
        "subject": subject or f"Change {change_id}",
        "patchset": patchset,
        "author": author,
        "url": url,
        "jobs": jobs,
    }


def _collect_jobs(redis: TorriRedis, pipeline_name: str, change_id: str) -> List[dict]:
    """Scan Redis for all job keys belonging to this change+pipeline."""
    pattern = f"torri:job:{pipeline_name}:{change_id}:*"
    try:
        keys = list(redis.client.scan_iter(pattern))
    except Exception as e:
        logger.error("Error scanning job keys for %s/%s: %s", pipeline_name, change_id, e)
        return []

    jobs = []
    for key in keys:
        data = redis.get_state(key)
        if data:
            jobs.append({
                "job_id": data.get("job_id", key),
                "job_name": data.get("job_name", ""),
                "status": data.get("status", "queued"),
                "start_time": data.get("start_time"),
                "end_time": data.get("end_time"),
                "url": None,
            })
    return jobs
