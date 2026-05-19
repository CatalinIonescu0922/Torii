"""
Merger client for the scheduler.

Sends a MergeRequest to the merger via Kafka and waits for the MergeResponse
on the merger-responses topic. The response carries the merged_commit_hash
(synthetic ref) that jobs need to check out the speculative merge result.

Usage:
    request_merge(
        job_id="check:1:abc123",
        project="libraries/common-utils",
        branch="master",
        patchset_refs=["refs/changes/01/1/1"],
        on_done=lambda ref, error: ...,
    )
"""

import os
import json
import threading
import uuid
import logging
from typing import Callable, Optional

from confluent_kafka import Consumer, KafkaError

from torri.kafka.producer import KafkaProducerClient

logger = logging.getLogger("torri.scheduler.merger_client")

_REQUEST_TOPIC = os.getenv("KAFKA_MERGER_INPUT_TOPIC", "merger-requests")
_RESPONSE_TOPIC = os.getenv("KAFKA_MERGER_OUTPUT_TOPIC", "merger-responses")
_TIMEOUT_SECONDS = int(os.getenv("MERGER_TIMEOUT_SECONDS", "120"))


def request_merge(
    job_id: str,
    project: str,
    branch: str,
    patchset_refs: list[str],
    on_done: Callable[[Optional[str], Optional[str]], None],
) -> None:
    """
    Send a speculative merge request to the merger and wait for the response.

    Spawns a background thread that:
      1. Publishes MergeRequest to merger-requests
      2. Polls merger-responses until it sees the matching job_id
      3. Calls on_done(merged_commit_hash, error_message)
         — on_done(ref, None)   on success
         — on_done(None, error) on failure / timeout

    Does not block the calling thread.
    """
    t = threading.Thread(
        target=_merge_worker,
        args=(job_id, project, branch, patchset_refs, on_done),
        daemon=True,
        name=f"merger-{job_id}",
    )
    t.start()


def _merge_worker(
    job_id: str,
    project: str,
    branch: str,
    patchset_refs: list[str],
    on_done: Callable[[Optional[str], Optional[str]], None],
) -> None:
    kafka_server = os.getenv("KAFKA_SERVER", "kafka:9092")

    producer = KafkaProducerClient(kafka_server)
    consumer = Consumer({
        "bootstrap.servers": kafka_server,
        "group.id": f"scheduler-merger-response-{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })
    consumer.subscribe([_RESPONSE_TOPIC])

    payload = {
        "job_id": job_id,
        "target_repository": project,
        "base_branch": branch,
        "patchset_refs": patchset_refs,
        "action": "SPECULATIVE_MERGE",
    }

    try:
        logger.info(
            "Sending merge request job_id=%s project=%s branch=%s refs=%s",
            job_id, project, branch, patchset_refs,
        )
        producer.send_message(_REQUEST_TOPIC, key=job_id, value=json.dumps(payload))
        producer.flush()

        deadline = _TIMEOUT_SECONDS
        elapsed = 0
        poll_interval = 1.0

        while elapsed < deadline:
            msg = consumer.poll(timeout=poll_interval)
            elapsed += poll_interval

            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Kafka error polling merger-responses: %s", msg.error())
                continue

            try:
                response = json.loads(msg.value().decode("utf-8"))
            except Exception as e:
                logger.warning("Unreadable merger response: %s", e)
                continue

            if response.get("job_id") != job_id:
                # Not our response — leave it for other consumers (different group_id handles this)
                continue

            status = response.get("status")
            if status == "SUCCESS":
                ref = response.get("merged_commit_hash")
                logger.info("Merge succeeded job_id=%s ref=%s", job_id, ref)
                on_done(ref, None)
            else:
                error = response.get("error_message") or f"Merge failed: {status}"
                logger.error("Merge failed job_id=%s status=%s error=%s", job_id, status, error)
                on_done(None, error)
            return

        logger.error("Merger request timed out after %ds job_id=%s", deadline, job_id)
        on_done(None, f"Merger timed out after {deadline}s")

    except Exception as e:
        logger.error("Unexpected error in merger worker job_id=%s: %s", job_id, e, exc_info=True)
        on_done(None, str(e))
    finally:
        consumer.close()
