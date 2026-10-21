"""Logging configuration for runtime diagnostics."""

from __future__ import annotations

from logging.handlers import RotatingFileHandler
from pathlib import Path
import logging as std_logging
import os
import re
import stat
import traceback
from urllib.parse import unquote_plus

from worklogger.config.constants import (
    LOG_BACKUP_COUNT,
    LOG_FILENAME,
    LOG_FORMAT,
    LOG_MAX_BYTES,
)

_HANDLER_MARKER = "_worklogger_file_handler"


class SensitiveDataFilter(std_logging.Filter):
    """Redact explicit credentials while retaining diagnostic identifiers."""

    _NAMES = r"(?:api[_-]?key|password|recovery[_-]?key|refresh[_-]?token|remember[_-]?token|access[_-]?token|id[_-]?token|token|client[_-]?secret|code[_-]?verifier|authorization|pkce|auth code)"
    _CREDENTIAL = re.compile(r'''(["']?\b''' + _NAMES + r'''\b["']?\s*[=:]\s*)(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\r\n,;&]+)''', re.IGNORECASE)
    _AUTHORIZATION = re.compile(r"\b(?:Bearer|Basic)\s+[^\s\"',;&]+", re.IGNORECASE)
    _USERINFO = re.compile(r"(https?://)[^/\s?#]*@", re.IGNORECASE)
    _QUERY_VALUE = re.compile(r"([?&])([^=\s&#]+)=([^\s&#\"']*)")
    _QUERY_NAME = re.compile(_NAMES + r"|code", re.IGNORECASE)

    def filter(self, record: std_logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = "Log message formatting failed"
        record.msg = self._redact(message)
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
        def redact_query(match):
            if cls._QUERY_NAME.fullmatch(unquote_plus(match[2])):
                return match[1] + match[2] + "=[redacted]"
            return match[0]
        message = cls._QUERY_VALUE.sub(redact_query, message)
        message = cls._USERINFO.sub(r"\1[redacted]@", message)
        message = cls._AUTHORIZATION.sub("Authorization [redacted]", message)
        return cls._CREDENTIAL.sub(r"\1[redacted]", message)


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
    descriptor = _open_log(path)
    os.close(descriptor)

    level = std_logging.DEBUG if _debug_enabled(debug) else std_logging.INFO
    root = std_logging.getLogger()
    root.setLevel(level)
    from worklogger.infrastructure.exception_hooks import install_exception_hooks
    install_exception_hooks()

    existing = _existing_worklogger_handler(root)
    if existing is not None:
        existing_path = Path(getattr(existing, "baseFilename", "")).resolve()
        if existing_path == path.resolve():
            existing.setLevel(level)
            return path
        root.removeHandler(existing)
        existing.close()

    handler = _PrivateRotatingFileHandler(
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


class _PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        descriptor = _open_log(Path(self.baseFilename))
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            return os.fdopen(descriptor, self.mode, encoding=self.encoding, errors=self.errors)
        except Exception:
            os.close(descriptor)
            raise


def _open_log(path):
    if path.is_symlink():
        raise OSError("log_destination_invalid")
    descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        opened, current = os.fstat(descriptor), path.lstat()
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or not stat.S_ISREG(current.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)):
            raise OSError("log_destination_invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def log_file_path() -> Path:
    """Return the configured log destination without creating files."""
    return _resolve_log_path(None, frozen=None)


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
    from worklogger.infrastructure.database.paths import default_database_path
    return default_database_path(frozen=frozen).parent / LOG_FILENAME


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
