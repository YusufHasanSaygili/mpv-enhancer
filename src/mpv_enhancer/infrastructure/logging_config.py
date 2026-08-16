"""Privacy-safe structured file logging."""

import copy
import json
import logging
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from mpv_enhancer.infrastructure.paths import AppDataPaths

DEFAULT_LOG_FILENAME = "mpv-enhancer.log"
REDACTED_PATH = "<redacted-path>"

_QUOTED_ABSOLUTE_PATH = re.compile(
    r"""(["'])(?:(?:[A-Za-z]:[\\/])|(?:\\\\)|/)[^"'\r\n]+\1"""
)
_UNQUOTED_ABSOLUTE_PATH = re.compile(
    r"(?<!\w)(?:[A-Za-z]:[\\/]|\\\\[^\\/\s]+[\\/]|/(?:[^/\s]+/)+)[^\s,;]+"
)


class RedactingJsonFormatter(logging.Formatter):
    """Render one redacted JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        safe_record.msg = _redact_value(record.msg)
        safe_record.args = _redact_arguments(record.args)

        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_paths(safe_record.getMessage()),
        }
        if record.exc_info and record.exc_info[1] is not None:
            exception = record.exc_info[1]
            payload["exception"] = {
                "type": type(exception).__name__,
                "message": redact_paths(str(exception)),
            }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class AppRotatingFileHandler(RotatingFileHandler):
    """Marker subclass for handlers managed by MPV Enhancer."""


def configure_logging(
    paths: AppDataPaths,
    *,
    logger_name: str = "mpv_enhancer",
    level: int = logging.INFO,
    max_bytes: int = 1_048_576,
    backup_count: int = 3,
) -> logging.Logger:
    """Configure an idempotent, rotating, privacy-safe application logger."""
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive.")
    if backup_count < 1:
        raise ValueError("backup_count must be positive.")

    paths.ensure_directories()
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False
    shutdown_logging(logger)

    handler = AppRotatingFileHandler(
        paths.log_dir / DEFAULT_LOG_FILENAME,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(RedactingJsonFormatter())
    logger.addHandler(handler)
    return logger


def shutdown_logging(logger: logging.Logger) -> None:
    """Flush, close, and detach handlers managed by this application."""
    for handler in list(logger.handlers):
        if isinstance(handler, AppRotatingFileHandler):
            handler.flush()
            handler.close()
            logger.removeHandler(handler)


def redact_paths(text: str) -> str:
    """Redact quoted and whitespace-free absolute paths embedded in text."""
    redacted = _QUOTED_ABSOLUTE_PATH.sub(REDACTED_PATH, text)
    return _UNQUOTED_ABSOLUTE_PATH.sub(REDACTED_PATH, redacted)


def _redact_arguments(arguments: Any) -> Any:
    if isinstance(arguments, tuple):
        return tuple(_redact_value(value) for value in arguments)
    if isinstance(arguments, Mapping):
        return {key: _redact_value(value) for key, value in arguments.items()}
    return _redact_value(arguments)


def _redact_value(value: Any) -> Any:
    if isinstance(value, os.PathLike):
        return REDACTED_PATH
    if isinstance(value, str):
        if _is_absolute_path(value):
            return REDACTED_PATH
        return redact_paths(value)
    return value


def _is_absolute_path(value: str) -> bool:
    return PureWindowsPath(value).is_absolute() or PurePosixPath(value).is_absolute()
