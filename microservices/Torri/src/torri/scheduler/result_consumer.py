"""
Result consumer — listens on the job-results Kafka topic and forwards
each completed job to executor_dispatcher.on_job_result().

Runs as a background thread inside the scheduler process.
Starts automatically when the scheduler starts.
"""

import json
import logging
import threading

from confluent_kafka import Consumer, KafkaError

from torri.scheduler import executor_dispatcher
from torri.scheduler.redis_client import TorriRedis
from torri.scheduler.status_writer import refresh_status

logger = logging.getLogger("torri.scheduler.result_consumer")

JOB_RESULTS_TOPIC = "job-results"


class ResultConsumer(threading.Thread):
    """Background thread that consumes job-results messages from Kafka."""

    def __init__(self, kafka_bootstrap: str, redis: TorriRedis, pipeline_names: list):
        super().__init__(daemon=True, name="ResultConsumer")
        self.kafka_bootstrap = kafka_bootstrap
        self.redis = redis
        self.pipeline_names = pipeline_names
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def run(self):
        consumer = Consumer({
            "bootstrap.servers": self.kafka_bootstrap,
            "group.id": "scheduler-result-consumer",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        })
        consumer.subscribe([JOB_RESULTS_TOPIC])
        logger.info("ResultConsumer started, listening on %s", JOB_RESULTS_TOPIC)

        try:
            while not self._stop_event.is_set():
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() != KafkaError._PARTITION_EOF:
                        logger.error("Kafka error: %s", msg.error())
                    continue

                self._handle(msg)
                consumer.commit(asynchronous=False)

        finally:
            consumer.close()
            logger.info("ResultConsumer stopped")

    def _handle(self, msg):
        try:
            result = json.loads(msg.value().decode("utf-8"))
        except Exception as e:
            logger.warning("Unreadable job-result message: %s", e)
            return

        job_uuid = result.get("job_uuid", "")
        buildset_uuid = result.get("buildset_uuid", "")
        job_name = result.get("job_name", "")
        status = result.get("status", "failure")

        if not job_uuid or not buildset_uuid:
            logger.warning("job-result missing job_uuid or buildset_uuid: %s", result)
            return

        logger.info(
            "Job result received: job=%s buildset=%s status=%s",
            job_name, buildset_uuid, status,
        )

        executor_dispatcher.on_job_result(job_uuid, buildset_uuid, job_name, status)
        refresh_status(self.redis, self.pipeline_names)
