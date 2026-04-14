"""DownloadController — manages the model download lifecycle.

Completely Qt-free: callbacks are plain callables invoked from the background
thread.  The UI layer (``LocalDownloadDialog``) bridges them to Qt signals.

Public API
----------
``DownloadController.get()``     — process singleton
``ctrl.start(entry_id, ...)``   — begin / resume download
``ctrl.cancel()``               — stop after current chunk
``ctrl.is_running``             — True while download in progress
``ctrl.get_progress()``         — (downloaded_bytes, total_bytes)
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable, Optional


class DownloadController:
    """Process-wide singleton that owns the model download lifecycle.

    All public methods are thread-safe.  Callbacks are invoked from the
    background download thread — callers must marshal to Qt themselves if
    needed (``LocalDownloadDialog`` uses direct signal emits which Qt queues
    automatically).
    """

    _instance:   Optional["DownloadController"] = None
    _class_lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._cancel_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._downloaded  = 0
        self._total       = 0

    # -- singleton ---------------------------------------------------------
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

    # -- status ------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def get_progress(self) -> tuple:
        with self._lock:
            return self._downloaded, self._total

    # -- control -----------------------------------------------------------
    def start(
        self,
        entry_id:    str = "local",
        progress_cb: Optional[Callable] = None,
        status_cb:   Optional[Callable] = None,
        done_cb:     Optional[Callable] = None,
        error_cb:    Optional[Callable] = None,
    ) -> None:
        """Start (or resume) download for *entry_id*.  No-op if already running."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._cancel_flag.clear()
            self._downloaded = 0
            self._total      = 0
            self._thread = threading.Thread(
                target=self._worker,
                args=(entry_id, progress_cb, status_cb, done_cb, error_cb),
                daemon=True,
            )
            self._thread.start()

    def cancel(self) -> None:
        """Request cancellation; the current chunk finishes first."""
        self._cancel_flag.set()

    # -- worker ------------------------------------------------------------
    def _worker(
        self,
        entry_id:    str,
        progress_cb: Optional[Callable],
        status_cb:   Optional[Callable],
        done_cb:     Optional[Callable],
        error_cb:    Optional[Callable],
    ) -> None:
        from services import local_model_service as lms

        def _st(key: str) -> None:
            if callable(status_cb):
                try:
                    status_cb(str(key))
                except Exception:
                    pass

        def _err(msg: str) -> None:
            if callable(error_cb):
                try:
                    error_cb(str(msg))
                except Exception:
                    pass

        try:
            # 1. Auto-install runtime deps (no-op if already present)
            _st("local_model_installing_deps")
            from services.dep_installer import ensure_download_deps
            ensure_download_deps()

            import httpx
            import portalocker

            # 2. Resolve paths
            models_dir = lms.get_models_dir()
            models_dir.mkdir(parents=True, exist_ok=True)
            manifest   = lms.load_manifest(models_dir)
            entry      = lms.get_entry(manifest, entry_id)
            filename   = entry.get("file", lms.MODEL_FILENAME)
            url        = entry.get("url",  lms.MODEL_URL)
            model_path = models_dir / filename
            temp_path  = models_dir / (filename + ".tmp")

            # 3. Already present and verified?
            if model_path.exists() and model_path.stat().st_size > 0:
                expected = entry.get("sha256", "").strip().lower()
                if expected and lms.sha256_of_file(model_path) == expected:
                    _st("local_model_status_ready")
                    if done_cb:
                        done_cb(model_path)
                    return
                model_path.unlink(missing_ok=True)

            # 4. Resume support
            lock_path   = models_dir / lms.LOCK_FILENAME
            resume_from = temp_path.stat().st_size if temp_path.exists() else 0
            headers: dict = {}
            if resume_from > 0:
                headers["Range"] = f"bytes={resume_from}-"

            _st("local_model_downloading")

            with portalocker.Lock(str(lock_path), timeout=2):
                with httpx.stream(
                    "GET", url,
                    headers=headers,
                    follow_redirects=True,
                    timeout=httpx.Timeout(connect=20.0, read=120.0,
                                          write=10.0, pool=5.0),
                ) as resp:
                    resp.raise_for_status()
                    content_length = int(resp.headers.get("content-length", 0))
                    with self._lock:
                        self._total      = resume_from + content_length
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
                            if progress_cb:
                                try:
                                    progress_cb(dl, tot)
                                except Exception:
                                    pass

            # 5. SHA-256 verification
            _st("local_model_verifying")
            expected_sha = entry.get("sha256", "").strip().lower()
            actual_sha   = lms.sha256_of_file(temp_path)

            if expected_sha and actual_sha != expected_sha:
                temp_path.unlink(missing_ok=True)
                _err("local_model_hash_fail")
                return

            # 6. Atomic rename; record hash
            shutil.move(str(temp_path), str(model_path))
            lms.update_sha256_in_manifest(actual_sha, models_dir, entry_id)
            _st("local_model_hash_ok")
            _st("local_model_download_ok")

            if callable(done_cb):
                try:
                    done_cb(model_path)
                except Exception:
                    pass

        except InterruptedError:
            _err("local_model_cancelled")
        except ImportError as exc:
            _err(f"local_model_dep_error: {exc}")
        except Exception as exc:
            # Translate known httpx exception types when available.
            try:
                import httpx as _hx
                if isinstance(exc, _hx.HTTPStatusError):
                    _err(f"HTTP {exc.response.status_code}")
                    return
                if isinstance(exc, _hx.TimeoutException):
                    _err("local_model_timeout")
                    return
            except ImportError:
                pass
            _err(str(exc))
