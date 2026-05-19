"""
Executor entry point.

Reads job-requests from Kafka and spawns a JobWorker thread per job.
A semaphore limits how many jobs run concurrently (max_workers from config).
"""

import json
import logging
import os
import signal
import threading
from pathlib import Path

from confluent_kafka import Consumer, KafkaError

logger = logging.getLogger("executor.main")


def run_executor(args):
    """Main executor worker loop.
    
    Reads job-requests from Kafka and spawns JobWorker threads.
    """
    from executor.config import ExecutorConfig
    from executor.job_worker import JobWorker
    
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


def main():
    """CLI entry point for torri-executor."""
    from shared.logger_setup import setup_logging
    
    # Import TorriCLI from torri.cmd if available, otherwise use basic argparse
    try:
        from torri.cmd import TorriCLI
    except ImportError:
        # Fallback: create a minimal CLI
        import argparse
        class MinimalCLI:
            def __init__(self, description="Torri Executor"):
                self.parser = argparse.ArgumentParser(description=description)
                self.parser.add_argument('-d', '--nodaemon', action='store_true', help='Do not daemonize.')
                self.parser.add_argument('-c', '--config', help='Path to configuration file')
            def parse_args(self):
                return self.parser.parse_args()
            def run(self, main_func):
                args = self.parse_args()
                main_func(args)
        TorriCLI = MinimalCLI
    
    # Use shared logging config from /app/config/log/
    log_config = Path("/app/config/log/main_logging.yaml")
    
    # Resolve log paths relative to executor workspace (container /app)
    workspace_root = Path(os.getenv("EXECUTOR_WORKSPACE_PATH", "/app"))
    setup_logging(log_config, workspace_root)
    
    cli = TorriCLI(description="Torri Executor")
    cli.run(run_executor)


if __name__ == "__main__":
    main()
