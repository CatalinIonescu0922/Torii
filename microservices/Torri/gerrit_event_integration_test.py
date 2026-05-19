#!/usr/bin/env python3
"""Run Kafka + Gerrit connection layer integration harness.

Initializes and starts both Kafka consumer and Gerrit event processor.
Events from Kafka are enriched with Gerrit change details and delivered to scheduler list.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv

from gerrit.gerritconnection import GerritEventProcessor, GerritRestConnection
from kafka.kafka_client import KafkaConnection
from shared.logger_setup import get_logger, setup_logging


class SimpleScheduler:
    """Scheduler that collects events in a list."""

    def __init__(self) -> None:
        self.events: list = []

    def addEvent(self, event) -> None:
        """Append event to the list."""
        self.events.append(event)


def _default_log_config(service_root: Path) -> Path:
    return service_root / "config" / "log" / "main_logging.yaml"


def main() -> int:
    service_root = Path(__file__).resolve().parent
    load_dotenv(service_root / ".env")

    log_config_path = _default_log_config(service_root)
    setup_logging(log_config_path, service_root)

    logger = get_logger("torri.integration")

    # Read connection settings from environment
    kafka_server = os.getenv("KAFKA_SERVER", "kafka:9092")
    kafka_topic = os.getenv("KAFKA_INPUT_TOPIC", "gerrit-stream-events")
    kafka_group_id = os.getenv("KAFKA_GROUPID", "torri-integration")

    gerrit_url = os.getenv("GERRIT_URL", "http://localhost:8080")
    gerrit_user = os.getenv("GERRIT_USER", "torii")
    gerrit_password = os.getenv("GERRIT_PASSWORD", "")

    auth = (gerrit_user, gerrit_password) if gerrit_user and gerrit_password else None

    logger.info("Kafka config: server=%s topic=%s group_id=%s", kafka_server, kafka_topic, kafka_group_id)
    logger.info("Gerrit config: url=%s user=%s auth_enabled=%s", gerrit_url, gerrit_user, bool(auth))

    # Initialize connections
    gerrit_connection = GerritRestConnection(gerrit_url, auth=auth)
    scheduler = SimpleScheduler()
    gerrit_connection.registerScheduler(scheduler)

    kafka_connection = KafkaConnection()
    processor = GerritEventProcessor(kafka_connection, gerrit_connection)

    try:
        logger.info("Starting Kafka connection")
        kafka_connection.connect()
        
        logger.info("Starting Gerrit event processor")
        processor.start()

        logger.info("Integration harness running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1)

        return 0
    except KeyboardInterrupt:
        logger.info("Received Ctrl+C, stopping")
        return 0
    finally:
        logger.info("Total events received: %s", len(scheduler.events))
        processor.stop()
        processor.join(timeout=5)
        kafka_connection.shutdown(wait=True, timeout=5)
        gerrit_connection.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    raise SystemExit(main())
