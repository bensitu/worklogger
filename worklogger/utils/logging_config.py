"""Application logging setup."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config.constants import LOG_FILENAME


def _log_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def configure_logging() -> None:
    """Configure a small rotating log file once per process."""
    root = logging.getLogger()
    if any(getattr(handler, "_worklogger_handler", False) for handler in root.handlers):
        return

    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    )
    try:
        os.makedirs(_log_dir(), exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(_log_dir(), LOG_FILENAME),
            maxBytes=512_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler._worklogger_handler = True
    root.addHandler(handler)
