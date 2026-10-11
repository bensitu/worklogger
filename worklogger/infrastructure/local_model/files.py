"""Validated model filenames, URLs, and cancellable file hashing."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from worklogger.infrastructure.http import validate_https_url


def safe_model_filename(filename: str) -> str:
    name = str(filename or "").strip()
    win_path = PureWindowsPath(name)
    if (
        not name
        or "/" in name
        or "\\" in name
        or ":" in name
        or Path(name).is_absolute()
        or win_path.is_absolute()
        or win_path.drive
        or name in {".", ".."}
        or ".." in Path(name).parts
        or any(ord(character) < 32 for character in name)
        or not name.lower().endswith((".gguf", ".gguf.tmp"))
    ):
        raise ValueError("local_model_filename_invalid")
    return name


def safe_model_url(url: str) -> str:
    try:
        return validate_https_url(url, public_only=True)
    except ValueError:
        raise ValueError("local_model_url_invalid")


def sha256_of_file(path: Path, *, is_cancelled: Callable[[], bool] | None = None) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            check_download_cancelled(is_cancelled)
            digest.update(chunk)
    return digest.hexdigest()


def check_download_cancelled(is_cancelled: Callable[[], bool] | None):
    if is_cancelled is not None and is_cancelled():
        raise InterruptedError("job_cancelled")
