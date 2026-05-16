"""Logging configuration for runtime diagnostics."""

from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging as std_logging
import os
import sys

from worklogger.config.constants import (
    LOG_BACKUP_COUNT,
    LOG_FILENAME,
    LOG_FORMAT,
    LOG_MAX_BYTES,
)

_HANDLER_MARKER = "_worklogger_file_handler"


class SensitiveDataFilter(std_logging.Filter):
    """Reject log records that are likely to contain sensitive credential data."""

    _SENSITIVE_WORDS = (
        "api_key",
        "auth code",
        "password",
        "pkce",
        "recovery_key",
        "refresh_token",
        "remember_token",
        "token",
    )

    def filter(self, record: std_logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        return not any(word in message for word in self._SENSITIVE_WORDS)


def setup_logging(
    log_path: Path | str | None = None,
    *,
    debug: bool | None = None,
    frozen: bool | None = None,
) -> Path:
    """Configure the root logger with a rotating WorkLogger file handler."""

    path = _resolve_log_path(log_path, frozen=frozen)
    path.parent.mkdir(parents=True, exist_ok=True)

    level = std_logging.DEBUG if _debug_enabled(debug) else std_logging.INFO
    root = std_logging.getLogger()
    root.setLevel(level)

    existing = _existing_worklogger_handler(root)
    if existing is not None:
        existing_path = Path(getattr(existing, "baseFilename", "")).resolve()
        if existing_path == path.resolve():
            existing.setLevel(level)
            return path
        root.removeHandler(existing)
        existing.close()

    handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    setattr(handler, _HANDLER_MARKER, True)
    handler.setLevel(level)
    handler.setFormatter(std_logging.Formatter(LOG_FORMAT))
    handler.addFilter(SensitiveDataFilter())
    root.addHandler(handler)
    std_logging.captureWarnings(True)
    return path


def _resolve_log_path(
    log_path: Path | str | None,
    *,
    frozen: bool | None,
) -> Path:
    if log_path is not None:
        return Path(log_path)
    env_path = os.environ.get("WORKLOGGER_LOG_PATH", "").strip()
    if env_path:
        return Path(env_path)
    if bool(getattr(sys, "frozen", False) if frozen is None else frozen):
        return Path(sys.executable).resolve().parent / LOG_FILENAME
    return Path.cwd() / LOG_FILENAME


def _debug_enabled(debug: bool | None) -> bool:
    if debug is not None:
        return bool(debug)
    return os.environ.get("WORKLOGGER_DEBUG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _existing_worklogger_handler(
    logger: std_logging.Logger,
) -> std_logging.Handler | None:
    for handler in logger.handlers:
        if bool(getattr(handler, _HANDLER_MARKER, False)):
            return handler
    return None
