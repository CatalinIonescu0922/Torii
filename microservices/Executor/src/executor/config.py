"""
Executor configuration.

Reads from an INI config file (executor.conf) using Python's built-in
configparser. The config file path defaults to the same directory as
this module, or can be overridden via EXECUTOR_CONF env var.
"""

import configparser
import os
from pathlib import Path


class ExecutorConfig:
    def __init__(self, config_file: str = None):
        if config_file is None:
            config_file = os.environ.get(
                "EXECUTOR_CONF",
                str(Path(__file__).resolve().parent / "executor.conf"),
            )

        self._config = configparser.ConfigParser()
        if not os.path.exists(config_file):
            raise FileNotFoundError(f"Executor config not found: {config_file}")
        self._config.read(config_file)

    def _get(self, section: str, key: str, fallback: str = "") -> str:
        return self._config.get(section, key, fallback=fallback)

    def _get_int(self, section: str, key: str, fallback: int = 0) -> int:
        return self._config.getint(section, key, fallback=fallback)

    # Kafka
    @property
    def kafka_bootstrap(self) -> str:
        return self._get("kafka", "bootstrap_servers", "kafka:9094")

    @property
    def kafka_group_id(self) -> str:
        return self._get("kafka", "group_id", "executor-group")

    @property
    def job_requests_topic(self) -> str:
        return self._get("kafka", "job_requests_topic", "job-requests")

    @property
    def job_results_topic(self) -> str:
        return self._get("kafka", "job_results_topic", "job-results")

    # Redis
    @property
    def redis_url(self) -> str:
        return self._get("redis", "url", "redis://redis:6379/0")

    # Executor runtime
    @property
    def job_dir(self) -> str:
        return self._get("executor", "job_dir", "/var/torii/jobs")

    @property
    def max_workers(self) -> int:
        return self._get_int("executor", "max_workers", 4)

    @property
    def use_bwrap(self) -> bool:
        return self._config.getboolean("executor", "use_bwrap", fallback=True)

    @property
    def nodes_config(self) -> str:
        """Path to nodes.yaml (VM pool definitions)."""
        return self._get("executor", "nodes_config", "/etc/torri/nodes.yaml")

    # Image label → Docker image mappings live under [images] section.
    # e.g.  python-slim = python:3.12-slim
    def get_image_for_label(self, label: str) -> str:
        try:
            return self._config.get("images", label)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return ""
