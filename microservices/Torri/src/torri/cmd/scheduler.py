from . import TorriCLI
import os
import time
import yaml
from pathlib import Path

import voluptuous as V

from shared.logger_setup import get_logger, setup_logging
from shared.layout_validator import Validator
from torri.config.config_manager import ConfigurationManager
from torri.kafka.kafka_client import KafkaConnection
from torri.gerrit.gerritconnection import GerritEventProcessor, GerritRestConnection
from torri.scheduler.scheduler_queue import SchedulerQueue


def _validate_yaml_files(yaml_dir: str, logger):
    """Validate all three YAML files before starting. Raises on bad config."""
    logger.info("Validating YAML configuration files in %s", yaml_dir)

    jobs_data = _load_yaml(yaml_dir, "jobs.yaml")
    jobs_data, job_names = Validator.validate(jobs_data, "jobs.yaml")

    pipelines_data = _load_yaml(yaml_dir, "pipelines.yaml")
    pipelines_data, pipeline_names = Validator.validate(pipelines_data, "pipelines.yaml")

    projects_data = _load_yaml(yaml_dir, "projects.yaml")
    Validator.validate(
        projects_data, "projects.yaml",
        list_of_pipelines=pipeline_names,
        list_of_jobs=job_names,
    )

    logger.info(
        "YAML validation passed: %d jobs, %d pipelines, %d projects",
        len(job_names), len(pipeline_names),
        len(projects_data.get("projects", [])),
    )


def _load_yaml(yaml_dir: str, filename: str) -> dict:
    path = os.path.join(yaml_dir, filename)
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def main():
    cli = TorriCLI("Torii Scheduler")
    args = cli.parse_args()

    # Setup logging using the config file next to torii.conf
    service_root = Path(__file__).resolve().parents[3]
    log_config = service_root / "config" / "log" / "main_logging.yaml"
    setup_logging(log_config, service_root)

    logger = get_logger("torri.scheduler.main")
    logger.info("Starting Torii Scheduler")

    config = ConfigurationManager()

    # Resolve yaml_dir relative to torii.conf location so relative paths work
    yaml_dir = config.scheduler_config_dir
    if not os.path.isabs(yaml_dir):
        yaml_dir = os.path.join(os.path.dirname(config.config_file), yaml_dir)
    logger.info("Loading YAML config from %s", yaml_dir)

    try:
        _validate_yaml_files(yaml_dir, logger)
    except V.Invalid as e:
        logger.error("YAML configuration is invalid: %s", e)
        raise SystemExit(1)

    protocol = "https" if config.gerrit_rest_https else "http"
    gerrit_base_url = f"{protocol}://{config.gerrit_server}:{config.gerrit_rest_port}"
    gerrit_conn = GerritRestConnection(
        gerrit_base_url,
        auth=(config.gerrit_user, config.gerrit_password) if config.gerrit_password else None,
    )

    # Prefer the REDIS_URL env var the container injects; fall back to torii.conf values
    redis_url = (
        os.getenv("REDIS_URL")
        or f"redis://{config.redis_host}:{config.redis_port}/{config.redis_db}"
    )
    scheduler_queue = SchedulerQueue(gerrit_conn, yaml_dir=yaml_dir, redis_url=redis_url)

    # Wire the scheduler so GerritEventProcessor can deliver events to it
    gerrit_conn.sched = scheduler_queue

    kafka_conn = KafkaConnection()
    kafka_conn.connect()

    event_processor = GerritEventProcessor(kafka_conn, gerrit_conn)
    event_processor.start()

    scheduler_queue.start()
    logger.info("Scheduler running. Waiting for events...")

    try:
        while scheduler_queue.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    finally:
        event_processor.stop()
        scheduler_queue.stop()
        logger.info("Scheduler stopped")


def run_server(args):
    pass
