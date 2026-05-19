"""
Executor entry point.

Reads job-requests from Kafka and spawns a JobWorker thread per job.
A semaphore limits how many jobs run concurrently (max_workers from config).
"""

import json
import logging
import signal
import threading

from confluent_kafka import Consumer, KafkaError

from executor.config import ExecutorConfig
from executor.job_worker import JobWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("executor.main")


def main():
    config = ExecutorConfig()

    semaphore = threading.Semaphore(config.max_workers)
    stop_event = threading.Event()

    def _on_signal(signum, frame):
        logger.info("Signal %d received — shutting down", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    consumer = Consumer({
        "bootstrap.servers": config.kafka_bootstrap,
        "group.id": config.kafka_group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([config.job_requests_topic])
    logger.info("Executor started. Listening on %s", config.job_requests_topic)

    try:
        while not stop_event.is_set():
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("Kafka error: %s", msg.error())
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except Exception as e:
                logger.warning("Unreadable job-request: %s", e)
                consumer.commit(asynchronous=False)
                continue

            consumer.commit(asynchronous=False)

            job_uuid = payload.get("job_uuid", "unknown")
            logger.info("Accepted job=%s buildset=%s", job_uuid, payload.get("buildset_uuid", ""))

            # Acquire the semaphore before spawning — blocks here if max_workers
            # are already busy.  Released by the worker thread when it finishes.
            semaphore.acquire()

            worker = JobWorker(config, payload, semaphore)
            t = threading.Thread(target=worker.run, daemon=True, name=f"job-{job_uuid}")
            t.start()

    finally:
        consumer.close()
        logger.info("Executor stopped")
