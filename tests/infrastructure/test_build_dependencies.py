"""Native dependency provenance and runtime verification contracts."""

from pathlib import Path
import hashlib
import io
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from packaging.tags import sys_tags
from scripts import lock_environment
from worklogger.diagnostics import check_local_model_runtime
from worklogger.main import main


class BuildDependencyTests(unittest.TestCase):
    def test_native_distribution_checksum_is_verified_before_installation(self):
        from scripts.native_artifacts import verified_artifact, select_artifact
        manifest = Path(__file__).resolve().parents[2] / "requirements/native-artifacts.json"
        artifact = select_artifact(manifest, "0.3.19", source=True)
        self.assertTrue(artifact["filename"].endswith(".tar.gz"))
        with self.assertRaises(ValueError):
            select_artifact(manifest, "0.0.0", source=True)
        with tempfile.TemporaryDirectory() as directory:
            item = {"filename": "sample.whl", "url": "https://example.test/sample.whl",
                    "sha256": hashlib.sha256(b"Approved distribution").hexdigest()}
            with self.assertRaises(ValueError):
                verified_artifact(item, directory, opener=lambda *_args, **_kwargs: io.BytesIO(b"Changed distribution"))
            self.assertEqual(list(Path(directory).iterdir()), [])
            verified = verified_artifact(item, directory, opener=lambda *_args, **_kwargs: io.BytesIO(b"Approved distribution"))
            self.assertEqual(verified.read_bytes(), b"Approved distribution")
            verified.write_bytes(b"Changed cached distribution")
            with self.assertRaises(ValueError):
                verified_artifact(item, directory, opener=Mock(side_effect=AssertionError()))

    def test_lock_capture_records_prefetched_target_wheel_without_index_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requirements = root / "requirements-ai.txt"
            requirements.write_text("llama-cpp-python==0.3.19\n", encoding="utf-8")
            wheels = root / "wheels"
            wheels.mkdir()
            tag = next(sys_tags())
            wheel = wheels / f"llama_cpp_python-0.3.19-{tag}.whl"
            wheel.write_bytes(b"Synthetic native wheel")
            (wheels / "llama_cpp_python-0.3.19-py2-none-any.whl").write_bytes(b"Incompatible wheel")
            with (patch.object(lock_environment, "ROOT", root),
                  patch.object(lock_environment, "dependency_closure", return_value={"llama-cpp-python": "0.3.19"}),
                  patch.object(lock_environment.subprocess, "run", side_effect=AssertionError("unexpected_index_access"))):
                captured = lock_environment.capture_lock(root / "target.lock.json", [requirements], wheels)
                verified = lock_environment.verify_lock(root / "target.lock.json", installed={"llama-cpp-python": "0.3.19"})
            self.assertEqual(captured, verified)
            self.assertEqual(captured["packages"][0]["wheel"], wheel.name)
            self.assertEqual(captured["packages"][0]["sha256"], lock_environment.digest(wheel))

    def test_native_runtime_verification_initializes_and_releases_backend(self):
        native = SimpleNamespace(llama_backend_init=Mock(), llama_backend_free=Mock(),
                                 llama_print_system_info=Mock(return_value=b"Synthetic CPU backend"))
        with patch.dict("sys.modules", {"llama_cpp": native}):
            check_local_model_runtime()
        native.llama_backend_init.assert_called_once_with()
        native.llama_backend_free.assert_called_once_with()

    def test_native_runtime_verification_releases_backend_on_failure(self):
        native = SimpleNamespace(llama_backend_init=Mock(), llama_backend_free=Mock(),
                                 llama_print_system_info=Mock(return_value=b""))
        with patch.dict("sys.modules", {"llama_cpp": native}), self.assertRaises(RuntimeError):
            check_local_model_runtime()
        native.llama_backend_free.assert_called_once_with()

    def test_native_runtime_command_reports_missing_dependency_without_starting_desktop(self):
        desktop = Mock()
        with (patch("worklogger.diagnostics.check_local_model_runtime", side_effect=ImportError),
              patch("worklogger.main._safe_stdout")):
            self.assertEqual(main(["--smoke-local-model-runtime"], desktop_runner=desktop), 1)
        desktop.assert_not_called()
