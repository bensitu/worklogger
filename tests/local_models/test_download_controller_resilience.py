import hashlib
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.download_controller import DownloadController


class _FakeLock:
    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False


class _FakeResponse:
    def __init__(self, status_code: int, chunks: list[bytes] | None = None, headers: dict | None = None):
        self.status_code = status_code
        self._chunks = list(chunks or [])
        self.headers = dict(headers or {})

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise _FakeHTTPStatusError(self)

    def iter_bytes(self, chunk_size: int = 65536):
        del chunk_size
        for c in self._chunks:
            yield c


class _FakeHTTPStatusError(Exception):
    def __init__(self, response: _FakeResponse):
        self.response = response
        super().__init__(f"HTTP {response.status_code}")


class _FakeTimeoutException(Exception):
    pass


def _make_fake_httpx(plans: list[object]):
    queue = list(plans)

    class _Timeout:
        def __init__(self, **_kwargs):
            pass

    def _stream(*_args, **_kwargs):
        if not queue:
            raise RuntimeError("No more fake httpx stream plans")
        plan = queue.pop(0)
        if isinstance(plan, Exception):
            raise plan
        return plan

    return SimpleNamespace(
        stream=_stream,
        Timeout=_Timeout,
        HTTPStatusError=_FakeHTTPStatusError,
        TimeoutException=_FakeTimeoutException,
    )


class DownloadControllerResilienceTests(unittest.TestCase):
    def _temp_models_dir(self, name: str) -> Path:
        root = (
            Path(PROJECT_ROOT)
            / "tests"
            / "_artifacts"
            / "download_resilience"
            / f"{name}_{uuid4().hex}"
        )
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_http_416_resets_partial_file_and_succeeds(self):
        models_dir = self._temp_models_dir("case_416")
        temp_path = models_dir / "demo.gguf.tmp"
        model_path = models_dir / "demo.gguf"
        temp_path.write_bytes(b"stale")
        expected_sha = hashlib.sha256(b"abc").hexdigest()

        fake_httpx = _make_fake_httpx(
            [
                _FakeResponse(416, chunks=[], headers={"content-length": "0"}),
                _FakeResponse(200, chunks=[b"abc"], headers={"content-length": "3"}),
            ]
        )
        fake_portalocker = SimpleNamespace(Lock=_FakeLock)

        statuses: list[str] = []
        errors: list[str] = []
        done = Mock()

        with patch("services.dep_installer.ensure_download_deps", return_value=None), \
             patch.dict("sys.modules", {"httpx": fake_httpx, "portalocker": fake_portalocker}), \
             patch("services.local_model_service.get_models_dir", return_value=models_dir), \
             patch("services.local_model_service.load_manifest", return_value=[{"id": "local", "filename": "demo.gguf", "download_url": "https://example/model", "sha256": expected_sha}]), \
             patch("services.local_model_service.get_entry", return_value={"id": "local", "filename": "demo.gguf", "download_url": "https://example/model", "sha256": expected_sha}), \
             patch("services.local_model_service.sha256_of_file", side_effect=lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
            patch("services.local_model_service.update_sha256_in_manifest") as mock_update, \
             patch("services.local_model_service.LocalModelService") as mock_lms_cls:
            mock_lms_cls.get.return_value.unload_provider.return_value = None
            ctl = DownloadController()
            def _fake_unlink(path: Path, attempts: int = 3) -> bool:
                del attempts
                if path.exists():
                    path.write_bytes(b"")
                return True
            ctl._unlink_with_retry = _fake_unlink  # type: ignore[method-assign]
            ctl._replace_with_retry = lambda src, dst, attempts=3: dst.write_bytes(Path(src).read_bytes())  # type: ignore[method-assign]
            ctl._worker(
                "local",
                progress_cb=None,
                status_cb=lambda s: statuses.append(str(s)),
                done_cb=lambda p: done(p),
                error_cb=lambda e: errors.append(str(e)),
            )

        self.assertTrue(model_path.exists())
        self.assertEqual(model_path.read_bytes(), b"abc")
        self.assertTrue(any("local_model_hash_ok" in s for s in statuses))
        self.assertEqual(len(errors), 0)
        self.assertEqual(done.call_count, 1)
        self.assertEqual(mock_update.call_count, 1)

    def test_timeout_retries_then_cleanup_tmp_and_retry_once(self):
        models_dir = self._temp_models_dir("case_timeout_cleanup")
        stale_tmp = models_dir / "stale_chunk.tmp"
        stale_tmp.write_bytes(b"old")
        expected_sha = hashlib.sha256(b"xyz").hexdigest()

        fake_httpx = _make_fake_httpx(
            [
                _FakeTimeoutException("t1"),
                _FakeTimeoutException("t2"),
                _FakeTimeoutException("t3"),
                _FakeResponse(200, chunks=[b"xyz"], headers={"content-length": "3"}),
            ]
        )
        fake_portalocker = SimpleNamespace(Lock=_FakeLock)

        statuses: list[str] = []
        errors: list[str] = []
        done = Mock()

        with patch("services.dep_installer.ensure_download_deps", return_value=None), \
             patch.dict("sys.modules", {"httpx": fake_httpx, "portalocker": fake_portalocker}), \
             patch("services.local_model_service.get_models_dir", return_value=models_dir), \
             patch("services.local_model_service.load_manifest", return_value=[{"id": "local", "filename": "demo.gguf", "download_url": "https://example/model", "sha256": expected_sha}]), \
             patch("services.local_model_service.get_entry", return_value={"id": "local", "filename": "demo.gguf", "download_url": "https://example/model", "sha256": expected_sha}), \
             patch("services.local_model_service.sha256_of_file", side_effect=lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()), \
             patch("services.local_model_service.update_sha256_in_manifest"), \
             patch("services.local_model_service.LocalModelService") as mock_lms_cls:
            mock_lms_cls.get.return_value.unload_provider.return_value = None
            ctl = DownloadController()
            ctl._cleanup_tmp_files = lambda _models_dir: [stale_tmp]  # type: ignore[method-assign]
            ctl._replace_with_retry = lambda src, dst, attempts=3: dst.write_bytes(Path(src).read_bytes())  # type: ignore[method-assign]
            ctl._worker(
                "local",
                progress_cb=None,
                status_cb=lambda s: statuses.append(str(s)),
                done_cb=lambda p: done(p),
                error_cb=lambda e: errors.append(str(e)),
            )

        self.assertEqual(len(errors), 0)
        self.assertEqual(done.call_count, 1)
        self.assertTrue(any("Removed stale temp files" in s for s in statuses))

    def test_locked_temp_file_returns_detailed_help_message(self):
        models_dir = self._temp_models_dir("case_lock")
        temp_path = models_dir / "demo.gguf.tmp"
        expected_sha = hashlib.sha256(b"ok").hexdigest()

        fake_httpx = _make_fake_httpx(
            [_FakeResponse(200, chunks=[b"ok"], headers={"content-length": "2"}) for _ in range(4)]
        )
        fake_portalocker = SimpleNamespace(Lock=_FakeLock)

        statuses: list[str] = []
        errors: list[str] = []

        real_open = open

        def _open_with_lock(path, mode="r", *args, **kwargs):
            if Path(path) == temp_path and mode == "ab":
                raise PermissionError("[WinError 32] The process cannot access the file")
            return real_open(path, mode, *args, **kwargs)

        with patch("services.dep_installer.ensure_download_deps", return_value=None), \
             patch.dict("sys.modules", {"httpx": fake_httpx, "portalocker": fake_portalocker}), \
             patch("services.local_model_service.get_models_dir", return_value=models_dir), \
             patch("services.local_model_service.load_manifest", return_value=[{"id": "local", "filename": "demo.gguf", "download_url": "https://example/model", "sha256": expected_sha}]), \
             patch("services.local_model_service.get_entry", return_value={"id": "local", "filename": "demo.gguf", "download_url": "https://example/model", "sha256": expected_sha}), \
             patch("services.local_model_service.LocalModelService") as mock_lms_cls, \
             patch("builtins.open", side_effect=_open_with_lock):
            mock_lms_cls.get.return_value.unload_provider.return_value = None
            ctl = DownloadController()
            ctl._worker(
                "local",
                progress_cb=None,
                status_cb=lambda s: statuses.append(str(s)),
                done_cb=None,
                error_cb=lambda e: errors.append(str(e)),
            )

        self.assertTrue(errors)
        self.assertIn("WinError 32", errors[-1])
        self.assertIn("Troubleshooting", errors[-1])
        self.assertTrue(any("retrying" in s.lower() for s in statuses))


if __name__ == "__main__":
    unittest.main()

