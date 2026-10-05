"""Logging configuration for runtime diagnostics."""

from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging as std_logging
import os
import sys
import re
import traceback

from worklogger.config.constants import (
    LOG_BACKUP_COUNT,
    LOG_FILENAME,
    LOG_FORMAT,
    LOG_MAX_BYTES,
)

_HANDLER_MARKER = "_worklogger_file_handler"


class SensitiveDataFilter(std_logging.Filter):
    """Redact explicit credentials while retaining diagnostic identifiers."""

    _CREDENTIAL = re.compile(r"(?i)(\b(?:api[_-]?key|password|recovery[_-]?key|refresh[_-]?token|remember[_-]?token|access[_-]?token|token|client_secret|code_verifier|authorization|pkce|auth code)\b\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&]+)")
    _BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")

    def filter(self, record: std_logging.LogRecord) -> bool:
        record.msg = self._redact(record.getMessage())
        record.args = ()
        for key, value in tuple(record.__dict__.items()):
            if key not in {"msg", "args", "exc_info", "exc_text"} and self._CREDENTIAL.match(key + "=value"):
                record.__dict__[key] = "[redacted]"
            elif isinstance(value, str):
                record.__dict__[key] = self._redact(value)
        record.exc_text = None
        return True

    @classmethod
    def _redact(cls, message: str) -> str:
        return cls._CREDENTIAL.sub(r"\1[redacted]", cls._BEARER.sub("Bearer [redacted]", message))


class DiagnosticFormatter(std_logging.Formatter):
    """Keep exception types and locations without arbitrary exception payloads."""

    def formatException(self, exc_info) -> str:
        error_type, _error, trace = exc_info
        frames = [f"  {Path(frame.filename).name}:{frame.lineno} in {frame.name}" for frame in traceback.extract_tb(trace)]
        return "\n".join(["Traceback:", *frames, error_type.__name__])


def setup_logging(
    log_path: Path | str | None = None,
    *,
    debug: bool | None = None,
    frozen: bool | None = None,
) -> Path:
    """Configure the root logger with a rotating WorkLogger file handler."""

    path = _resolve_log_path(log_path, frozen=frozen)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    os.close(descriptor)

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
    handler.setFormatter(DiagnosticFormatter(LOG_FORMAT))
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
        from worklogger.infrastructure.database.paths import default_database_path
        return default_database_path(frozen=True).parent / LOG_FILENAME
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
