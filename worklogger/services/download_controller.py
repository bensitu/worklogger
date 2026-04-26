"""DownloadController — manages the model download lifecycle.

Completely Qt-free: callbacks are plain callables invoked from the background
thread. The UI layer (``LocalDownloadDialog``) bridges them to Qt signals.

Public API
----------
``DownloadController.get()``     — process singleton
``ctrl.start(entry_id, ...)``   — begin / resume download
``ctrl.cancel()``               — stop after current chunk
``ctrl.is_running``             — True while download in progress
``ctrl.get_progress()``         — (downloaded_bytes, total_bytes)
"""

from __future__ import annotations

import errno
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional

_MAX_RETRIES = 3
_LOCK_TIMEOUT_S = 2.0


class _RetryableDownloadError(Exception):
    """Internal marker exception for retryable download failures."""


class DownloadController:
    """Process-wide singleton that owns the model download lifecycle.

    All public methods are thread-safe. Callbacks are invoked from the
    background download thread. Callers must marshal to Qt themselves when
    needed (``LocalDownloadDialog`` emits Qt signals directly).
    """

    _instance: Optional["DownloadController"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._downloaded = 0
        self._total = 0

    @classmethod
    def get(cls) -> "DownloadController":
        with cls._class_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._class_lock:
            cls._instance = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def get_progress(self) -> tuple[int, int]:
        with self._lock:
            return self._downloaded, self._total

    def start(
        self,
        entry_id: str = "local",
        progress_cb: Optional[Callable] = None,
        status_cb: Optional[Callable] = None,
        done_cb: Optional[Callable] = None,
        error_cb: Optional[Callable] = None,
    ) -> None:
        """Start (or resume) download for *entry_id*.

        This is a no-op if a download thread is already running.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._cancel_flag.clear()
            self._downloaded = 0
            self._total = 0
            self._thread = threading.Thread(
                target=self._worker,
                args=(entry_id, progress_cb, status_cb, done_cb, error_cb),
                daemon=True,
            )
            self._thread.start()

    def cancel(self) -> None:
        """Request cancellation; the current chunk finishes first."""
        self._cancel_flag.set()

    def _unlink_with_retry(self, path: Path, attempts: int = 3) -> bool:
        """Try deleting *path* with small backoff retries."""
        for idx in range(max(1, attempts)):
            try:
                path.unlink(missing_ok=True)
                return True
            except PermissionError:
                # Some Windows setups keep a stale handle briefly. Try truncating
                # the file first and then retry deletion.
                try:
                    with open(path, "wb"):
                        pass
                    path.unlink(missing_ok=True)
                    return True
                except Exception:
                    pass
                if idx == attempts - 1:
                    return False
                time.sleep(0.2 * (idx + 1))
            except OSError:
                return False
        return False

    def _replace_with_retry(self, src: Path, dst: Path, attempts: int = 3) -> None:
        """Move *src* to *dst* with retries for transient Windows lock errors."""
        for idx in range(max(1, attempts)):
            try:
                shutil.move(str(src), str(dst))
                return
            except PermissionError as exc:
                if idx == attempts - 1:
                    raise PermissionError(
                        errno.EACCES,
                        (
                            f"WinError 32: cannot finalize model file '{dst}'. "
                            "A process still holds the file handle."
                        ),
                    ) from exc
                time.sleep(0.25 * (idx + 1))

    def _cleanup_tmp_files(self, models_dir: Path) -> list[Path]:
        """Delete stale `.tmp` files under models_dir and return removed paths."""
        removed: list[Path] = []
        for candidate in models_dir.glob("*.tmp"):
            if self._unlink_with_retry(candidate, attempts=3):
                removed.append(candidate)
        return removed

    @staticmethod
    def _backoff_seconds(attempt_no: int) -> float:
        return min(4.0, 0.6 * (2 ** max(0, attempt_no - 1)))

    @staticmethod
    def _help_text(temp_path: Path, last_error: str, attempts: int) -> str:
        return "\n".join(
            [
                "Local model download failed after retries.",
                f"Attempts: {attempts}",
                f"Temporary file: {temp_path}",
                f"Last error: {last_error}",
                "Troubleshooting:",
                "1. Close Settings > AI dialogs and stop other WorkLogger instances.",
                "2. Ensure no process is using the .tmp file, then retry download.",
                "3. Check network/proxy/VPN and try again.",
                "4. If repeated 416 errors occur, remove stale .tmp files in models/.",
            ]
        )

    def _worker(
        self,
        entry_id: str,
        progress_cb: Optional[Callable],
        status_cb: Optional[Callable],
        done_cb: Optional[Callable],
        error_cb: Optional[Callable],
    ) -> None:
        from services import local_model_service as lms

        def _st(text: str) -> None:
            if callable(status_cb):
                try:
                    status_cb(str(text))
                except Exception:
                    pass

        def _err(text: str) -> None:
            if callable(error_cb):
                try:
                    error_cb(str(text))
                except Exception:
                    pass

        try:
            _st("local_model_installing_deps")
            from services.dep_installer import ensure_download_deps

            ensure_download_deps()

            import httpx
            import portalocker

            models_dir = lms.get_models_dir()
            models_dir.mkdir(parents=True, exist_ok=True)
            manifest = lms.load_manifest(models_dir)
            entry = lms.get_entry(manifest, entry_id)
            filename = lms.validate_model_filename(
                entry.get("file", lms.MODEL_FILENAME)
            )
            url = lms.validate_model_url(entry.get("url", lms.MODEL_URL))
            model_path = lms.resolve_model_path(models_dir, filename)
            temp_path = lms.resolve_model_path(models_dir, filename + ".tmp")
            lock_path = models_dir / lms.LOCK_FILENAME

            try:
                lms.LocalModelService.get().unload_provider()
                lms.LocalModelService.reset()
            except Exception:
                pass

            if model_path.exists() and model_path.stat().st_size > 0:
                expected = entry.get("sha256", "").strip().lower()
                if expected and lms.sha256_of_file(model_path) == expected:
                    _st("local_model_status_ready")
                    if callable(done_cb):
                        done_cb(model_path)
                    return
                self._unlink_with_retry(model_path, attempts=2)

            attempt_no = 0
            cleanup_retry_used = False
            last_error = ""

            while True:
                if self._cancel_flag.is_set():
                    raise InterruptedError("Cancelled by user.")

                attempt_no += 1
                try:
                    resume_from = temp_path.stat().st_size if temp_path.exists() else 0
                    headers: dict[str, str] = {}
                    if resume_from > 0:
                        headers["Range"] = f"bytes={resume_from}-"

                    if attempt_no == 1:
                        _st("local_model_downloading")
                    else:
                        _st(f"Retrying local model download ({attempt_no})...")

                    with portalocker.Lock(str(lock_path), timeout=_LOCK_TIMEOUT_S):
                        try:
                            with open(temp_path, "ab"):
                                pass
                        except PermissionError as exc:
                            raise PermissionError(
                                errno.EACCES,
                                (
                                    f"WinError 32: cannot access temporary file '{temp_path}'. "
                                    "It may be used by another process."
                                ),
                            ) from exc

                        with httpx.stream(
                            "GET",
                            url,
                            headers=headers,
                            follow_redirects=True,
                            timeout=httpx.Timeout(
                                connect=20.0,
                                read=120.0,
                                write=10.0,
                                pool=5.0,
                            ),
                        ) as resp:
                            if resume_from > 0 and resp.status_code == 416:
                                if not self._unlink_with_retry(temp_path, attempts=3):
                                    raise PermissionError(
                                        errno.EACCES,
                                        (
                                            f"HTTP 416 and failed to delete '{temp_path}'. "
                                            "The temp file is still in use."
                                        ),
                                    )
                                raise _RetryableDownloadError(
                                    "HTTP 416 Range Not Satisfiable. Corrupted partial file was removed."
                                )

                            if resume_from > 0 and resp.status_code == 200:
                                if not self._unlink_with_retry(temp_path, attempts=3):
                                    raise PermissionError(
                                        errno.EACCES,
                                        (
                                            f"Range resume rejected and failed to reset '{temp_path}'. "
                                            "The temp file is still in use."
                                        ),
                                    )
                                raise _RetryableDownloadError(
                                    "Server ignored Range header. Restarted full download from zero."
                                )

                            resp.raise_for_status()

                            content_length = int(resp.headers.get("content-length", 0))
                            with self._lock:
                                self._total = resume_from + content_length
                                self._downloaded = resume_from

                            file_mode = "ab" if resume_from > 0 else "wb"
                            with open(temp_path, file_mode) as fh:
                                for chunk in resp.iter_bytes(chunk_size=65536):
                                    if self._cancel_flag.is_set():
                                        raise InterruptedError("Cancelled by user.")
                                    fh.write(chunk)
                                    with self._lock:
                                        self._downloaded += len(chunk)
                                        dl, tot = self._downloaded, self._total
                                    if callable(progress_cb):
                                        try:
                                            progress_cb(dl, tot)
                                        except Exception:
                                            pass

                    _st("local_model_verifying")
                    expected_sha = entry.get("sha256", "").strip().lower()
                    actual_sha = lms.sha256_of_file(temp_path)

                    if expected_sha and actual_sha != expected_sha:
                        self._unlink_with_retry(temp_path, attempts=3)
                        raise _RetryableDownloadError(
                            "Model integrity check failed after download (hash mismatch)."
                        )

                    self._replace_with_retry(temp_path, model_path, attempts=3)
                    lms.update_sha256_in_manifest(actual_sha, models_dir, entry_id)
                    _st("local_model_hash_ok")
                    _st("local_model_download_ok")

                    if callable(done_cb):
                        try:
                            done_cb(model_path)
                        except Exception:
                            pass
                    return

                except InterruptedError:
                    raise
                except _RetryableDownloadError as exc:
                    last_error = str(exc)
                except httpx.TimeoutException as exc:
                    last_error = f"Download timeout: {exc}"
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code if exc.response else 0
                    if status_code == 416 and temp_path.exists():
                        if self._unlink_with_retry(temp_path, attempts=3):
                            last_error = (
                                "HTTP 416 Range Not Satisfiable. "
                                "Corrupted partial file was removed."
                            )
                        else:
                            last_error = (
                                "HTTP 416 Range Not Satisfiable. "
                                "Unable to remove temporary file because it is in use."
                            )
                    else:
                        last_error = f"HTTP {status_code}: {exc}"
                except PermissionError as exc:
                    txt = str(exc)
                    if "WinError 32" not in txt:
                        txt = (
                            f"WinError 32/permission issue on '{temp_path}': {txt}"
                        )
                    last_error = txt
                except Exception as exc:
                    last_error = str(exc) or repr(exc)

                if attempt_no < _MAX_RETRIES:
                    wait_s = self._backoff_seconds(attempt_no)
                    _st(
                        "Download failed; retrying "
                        f"({attempt_no}/{_MAX_RETRIES - 1}) in {wait_s:.1f}s. "
                        f"Reason: {last_error}"
                    )
                    time.sleep(wait_s)
                    continue

                if not cleanup_retry_used:
                    removed = self._cleanup_tmp_files(models_dir)
                    cleanup_retry_used = True
                    if removed:
                        removed_names = ", ".join(p.name for p in removed[:3])
                        _st(
                            "Repeated failures detected. Removed stale temp files "
                            f"({removed_names}). Retrying once more..."
                        )
                        time.sleep(0.5)
                        continue

                _err(self._help_text(temp_path, last_error, attempt_no))
                return

        except InterruptedError:
            _err("local_model_cancelled")
        except ImportError as exc:
            _err(f"local_model_dep_error: {exc}")
        except Exception as exc:
            _err(str(exc) or repr(exc))
