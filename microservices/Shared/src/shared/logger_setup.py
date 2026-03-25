"""
Shared Logging  Configuration Manager
"""

import logging
import logging.config
import os
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Dict, Optional, Any

import yaml

_correlation_id: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)
_log_context: ContextVar[Dict[str, Any]] = ContextVar('log_context', default={})
_logging_configured: bool = False

_BASIC_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = _correlation_id.get() or 'N/A'
        context = _log_context.get()
        for key, value in context.items():
            setattr(record, key, value)
        if not hasattr(record, 'event_type'):
            record.event_type = 'N/A'
        return True


def _resolve_handler_paths(config: dict, service_root: Path) -> None:
    """Resolve relative filename entries in file handlers against service_root."""
    for handler_cfg in config.get('handlers', {}).values():
        if 'filename' not in handler_cfg:
            continue
        filename = Path(handler_cfg['filename'])
        if not filename.is_absolute():
            resolved = service_root / filename
            resolved.parent.mkdir(parents=True, exist_ok=True)
            handler_cfg['filename'] = str(resolved)


def _attach_context_filters(config: dict) -> None:
    """Attach ContextFilter to all configured handlers."""
    ctx_filter = ContextFilter()

    for handler in logging.root.handlers:
        handler.addFilter(ctx_filter)

    for logger_name in config.get('loggers', {}).keys():
        for handler in logging.getLogger(logger_name).handlers:
            handler.addFilter(ctx_filter)


def setup_logging(config_path: str | Path, service_root :Path) -> None:
    """
    Initialize logging from a YAML config file.
    Call once at service startup before any get_logger calls.

    File handler paths in the YAML are resolved relative to the SERVICE_ROOT
    env var. If SERVICE_ROOT is not set, falls back to cwd.

    Args:
        config_path: Absolute path to the logging YAML config file.
    """
    global _logging_configured

    if _logging_configured:
        return

    config_file = Path(config_path)

    if not config_file.exists():
        logging.basicConfig(level=logging.DEBUG, format=_BASIC_FORMAT)
        logging.getLogger(__name__).warning(
            "Logging config not found at %s, using basicConfig", config_file
        )
        _logging_configured = True
        return

    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)

    _resolve_handler_paths(config, service_root)
    logging.config.dictConfig(config)
    _attach_context_filters(config)

    _logging_configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger by name.

    Use dot notation for hierarchy:
        "Scheduler"              → main service logger
        "Scheduler.kafka_client" → sub-logger

    setup_logging() must be called first.
    """
    if not _logging_configured:
        logging.basicConfig(level=logging.DEBUG, format=_BASIC_FORMAT)
        logging.getLogger(__name__).warning(
            "get_logger('%s') called before setup_logging()", name
        )
    return logging.getLogger(name)


class log_context:
    def __init__(self, **kwargs):
        self.context = kwargs
        self.token = None

    def __enter__(self):
        current = _log_context.get().copy()
        current.update(self.context)
        self.token = _log_context.set(current)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            _log_context.reset(self.token)


class correlation_context:
    def __init__(self, correlation_id: Optional[str] = None):
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.token = None

    def __enter__(self):
        self.token = _correlation_id.set(self.correlation_id)
        return self.correlation_id

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            _correlation_id.reset(self.token)

