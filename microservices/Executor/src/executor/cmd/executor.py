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
    
    logger.info("[EXECUTOR] Loading configuration...")
    config = ExecutorConfig()
    logger.info("[EXECUTOR] Config loaded: kafka_bootstrap=%s group=%s topic=%s", config.kafka_bootstrap, config.kafka_group_id, config.job_requests_topic)
    logger.info("[EXECUTOR] max_workers=%d job_dir=%s use_bwrap=%s", config.max_workers, config.job_dir, config.use_bwrap)
    logger.info("[EXECUTOR] merger: host=%s port=%d user=%s workspace=%s", config.merger_host, config.merger_port, config.merger_user, config.merger_workspace_path)
    
    semaphore = threading.Semaphore(config.max_workers)
    logger.info("[EXECUTOR] Semaphore created with max_workers=%d", config.max_workers)
    stop_event = threading.Event()

    def _on_signal(signum, frame):
        logger.info("[EXECUTOR] Signal %d received — shutting down gracefully", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    logger.debug("[EXECUTOR] Signal handlers registered")

    logger.info("[EXECUTOR] Connecting to Kafka: %s", config.kafka_bootstrap)
    consumer = Consumer({
        "bootstrap.servers": config.kafka_bootstrap,
        "group.id": config.kafka_group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([config.job_requests_topic])
    logger.info("[EXECUTOR] Subscribed to Kafka topic: %s", config.job_requests_topic)

    try:
        while not stop_event.is_set():
            msg = consumer.poll(timeout=1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    logger.error("[EXECUTOR] Kafka consumer error: %s", msg.error())
                continue

            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except Exception as e:
                logger.error("[EXECUTOR] Failed to parse job-request: %s", e)
                consumer.commit(asynchronous=False)
                continue

            consumer.commit(asynchronous=False)

            job_uuid = payload.get("job_uuid", "unknown")
            buildset = payload.get("buildset_uuid", "unknown")
            project = payload.get("project", "unknown")
            logger.info("[EXECUTOR] Accepted job=%s buildset=%s project=%s", job_uuid, buildset, project)
            logger.debug("[EXECUTOR] Payload keys: %s", list(payload.keys()))

            # Acquire the semaphore before spawning — blocks here if max_workers
            # are already busy.  Released by the worker thread when it finishes.
            logger.debug("[EXECUTOR] Acquiring semaphore (active workers before: %d)", config.max_workers - semaphore._value)
            semaphore.acquire()
            logger.debug("[EXECUTOR] Semaphore acquired, spawning worker thread")

            worker = JobWorker(config, payload, semaphore)
            t = threading.Thread(target=worker.run, daemon=True, name=f"job-{job_uuid}")
            logger.info("[EXECUTOR] Spawning worker thread: %s", t.name)
            t.start()

    except Exception as e:
        logger.error("[EXECUTOR] Fatal error in executor loop: %s", e, exc_info=True)
    finally:
        logger.info("[EXECUTOR] Executor shutting down, closing Kafka consumer")
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
