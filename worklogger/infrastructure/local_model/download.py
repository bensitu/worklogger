"""Resumable, integrity-checked HTTPS downloads for local model files."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request

import portalocker

from worklogger.domain.local_model.models import DownloadProgress, is_sha256_digest
from worklogger.domain.shared.errors import CancellationError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.http import https_opener
from worklogger.infrastructure.local_model.files import check_download_cancelled, safe_model_url, sha256_of_file

UrlOpen = Callable[..., object]


class HttpRangeDownloader:
    def __init__(
        self,
        *,
        opener: UrlOpen | None = None,
        timeout_seconds: float = 30.0,
        chunk_size: int = 64 * 1024,
        max_bytes: int = 32 * 1024 ** 3,
    ) -> None:
        self._opener = opener or https_opener(public_only=True)
        self._timeout_seconds = float(timeout_seconds)
        self._chunk_size = int(chunk_size)
        self._max_bytes = int(max_bytes)
        if self._max_bytes < 1:
            raise ValueError("local_model_download_limit_invalid")
        if self._chunk_size < 1 or not math.isfinite(self._timeout_seconds) or self._timeout_seconds <= 0:
            raise ValueError("local_model_download_limit_invalid")

    def download(
        self,
        *,
        url: str,
        destination: Path,
        expected_sha256: str = "",
        is_cancelled: Callable[[], bool] | None = None,
        progress=None,
    ) -> Result[Path]:
        try:
            safe_url = safe_model_url(url)
            expected = str(expected_sha256 or "").strip().lower()
            if not is_sha256_digest(expected):
                return Result.failure(ValidationError("local_model_hash_required", "local_model_hash_required"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp_path = destination.with_suffix(destination.suffix + ".tmp")
            if temp_path.is_symlink() or (temp_path.exists() and not temp_path.is_file()):
                raise ValueError("local_model_filename_invalid")
            with portalocker.Lock(str(destination) + ".lock", timeout=0):
                _download_to_temp(
                    opener=self._opener, url=safe_url, destination=temp_path,
                    timeout_seconds=self._timeout_seconds, chunk_size=self._chunk_size,
                    is_cancelled=is_cancelled,
                    progress=progress,
                    max_bytes=self._max_bytes,
                )
                if progress is not None:
                    progress(DownloadProgress(temp_path.stat().st_size, temp_path.stat().st_size, "verification"))
                actual_sha = sha256_of_file(temp_path, is_cancelled=is_cancelled)
                if actual_sha != expected:
                    temp_path.unlink(missing_ok=True)
                    return Result.failure(
                        ValidationError("local_model_hash_mismatch", "local_model_hash_mismatch")
                    )
                check_download_cancelled(is_cancelled)
                os.replace(temp_path, destination)
            return Result.success(destination)
        except InterruptedError:
            return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
        except ValueError as exc:
            if str(exc) == "local_model_file_too_large":
                temp_path.unlink(missing_ok=True)
                return Result.failure(ValidationError(str(exc), str(exc)))
            return Result.failure(InfrastructureError("local_model_download_failed", "local_model_download_failed"))
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_download_failed",
                    "local_model_download_failed",
                    {"reason": type(exc).__name__},
                )
            )


def _download_to_temp(
    *,
    opener: UrlOpen,
    url: str,
    destination: Path,
    timeout_seconds: float,
    chunk_size: int,
    is_cancelled: Callable[[], bool] | None = None,
    progress=None,
    max_bytes: int = 32 * 1024 ** 3,
) -> None:
    check_download_cancelled(is_cancelled)
    resume_from = destination.stat().st_size if destination.exists() else 0
    if resume_from > max_bytes:
        raise ValueError("local_model_file_too_large")
    headers = {"Range": f"bytes={resume_from}-"} if resume_from > 0 else {}
    request = Request(url, headers=headers)
    try:
        response = opener(request, timeout=timeout_seconds)
    except HTTPError as exc:
        if exc.code == 416 and destination.exists():
            destination.unlink(missing_ok=True)
            resume_from = 0
            exc.close()
            response = opener(Request(url), timeout=timeout_seconds)
        else:
            raise
    except URLError:
        raise
    with response:
        status = getattr(response, "status", 200)
        headers = getattr(response, "headers", {})
        if status == 200:
            resume_from = 0
        elif status == 206:
            content_range = headers.get("Content-Range", "")
            match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
            if not match or int(match[1]) != resume_from or int(match[2]) < int(match[1]) or int(match[2]) >= int(match[3]):
                raise ValueError("local_model_range_invalid")
        else:
            raise ValueError("local_model_response_invalid")
        length = headers.get("Content-Length")
        expected_bytes = int(length) if length is not None else None
        if expected_bytes is not None and expected_bytes < 0:
            raise ValueError("local_model_response_invalid")
        if status == 206:
            range_length = int(match[2]) - int(match[1]) + 1
            if expected_bytes is not None and expected_bytes != range_length:
                raise ValueError("local_model_range_invalid")
            expected_bytes = range_length
        received = 0
        from time import monotonic
        last_progress = monotonic()
        total = int(match[3]) if status == 206 else expected_bytes
        if total is not None and total > max_bytes:
            raise ValueError("local_model_file_too_large")
        if progress is not None:
            progress(DownloadProgress(resume_from, total))
        mode = "ab" if resume_from > 0 else "wb"
        with destination.open(mode) as handle:
            while True:
                check_download_cancelled(is_cancelled)
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                if resume_from + received + len(chunk) > max_bytes:
                    raise ValueError("local_model_file_too_large")
                handle.write(chunk)
                received += len(chunk)
                if progress is not None and monotonic() - last_progress >= 0.1:
                    progress(DownloadProgress(resume_from + received, total))
                    last_progress = monotonic()
            handle.flush()
            os.fsync(handle.fileno())
        if expected_bytes is not None and received != expected_bytes:
            raise ValueError("local_model_response_incomplete")
        if progress is not None:
            progress(DownloadProgress(resume_from + received, total))
