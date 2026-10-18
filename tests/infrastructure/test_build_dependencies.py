"""Native dependency provenance and runtime verification contracts."""

from pathlib import Path
import hashlib
import io
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from packaging.tags import sys_tags, compatible_tags
from scripts import lock_environment
from worklogger.diagnostics import check_local_model_runtime
from worklogger.main import main


class BuildDependencyTests(unittest.TestCase):
    def test_native_wheel_selection_matches_python_and_platform_tags(self):
        from scripts.native_artifacts import select_artifact
        manifest = Path(__file__).resolve().parents[2] / "requirements/native-artifacts.json"
        for python in ((3, 11), (3, 12), (3, 13), (3, 14)):
            for platform in ("win_amd64", "manylinux_2_17_x86_64"):
                tags = list(compatible_tags(python_version=python, platforms=[platform]))
                with patch("scripts.native_artifacts.sys_tags", return_value=tags):
                    item = select_artifact(manifest, "0.3.36")
                self.assertIn("py3-none", item["filename"])
                self.assertIn(platform, item["filename"])
        for platform in ("win_arm64", "musllinux_1_2_x86_64", "macosx_11_0_arm64"):
            tags = list(compatible_tags(python_version=(3, 12), platforms=[platform]))
            with patch("scripts.native_artifacts.sys_tags", return_value=tags), self.assertRaises(ValueError):
                select_artifact(manifest, "0.3.36")

    def test_source_builds_preserve_platform_backends(self):
        from scripts import install_native_dependencies as installer
        root = Path(__file__).resolve().parents[2]
        for platform, source in (("win32", False), ("linux", False), ("linux", True), ("darwin", False)):
            with tempfile.TemporaryDirectory() as directory:
                wheel = Path(directory) / "native.whl"
                distribution = Path(directory) / ("native.tar.gz" if source or platform == "darwin" else "native.whl")
                with (patch.object(installer.sys, "platform", platform),
                      patch.object(installer, "select_artifact", return_value={}) as select,
                      patch.object(installer, "verified_artifact", return_value=distribution),
                      patch.object(installer, "compatible_wheels", return_value=[wheel]),
                      patch.object(installer, "install_dependencies") as install,
                      patch.object(installer.subprocess, "run") as execute):
                    installer.install_native_dependencies(Path(directory), from_source=source)
                build = source or platform == "darwin"
                select.assert_called_once_with(root / "requirements/native-artifacts.json", "0.3.36", source=build)
                self.assertEqual(execute.call_count, 1 if build else 0)
                install.assert_called_once_with((root / "requirements-ai.txt",), wheels=(wheel if build else distribution,),
                    lock_output=root / "build/native-dependencies.lock.txt",
                    constraints=(root / "requirements.txt", root / "requirements-build.txt"))
                if build:
                    environment = execute.call_args_list[0].kwargs["env"]
                    self.assertIn("-DGGML_NATIVE=OFF", environment["CMAKE_ARGS"])
                    if platform == "darwin":
                        self.assertIn("-DGGML_METAL=ON", environment["CMAKE_ARGS"])
                        self.assertIn("-DCMAKE_OSX_ARCHITECTURES=arm64", environment["CMAKE_ARGS"])
                    else:
                        for feature in ("AVX", "AVX2", "AVX512", "FMA", "F16C", "SSE42", "BMI2"):
                            self.assertIn(f"-DGGML_{feature}=OFF", environment["CMAKE_ARGS"])

    def test_wheel_archive_must_be_valid_even_when_its_checksum_matches(self):
        from scripts.native_artifacts import verified_artifact
        payload = b"Invalid wheel archive"
        item = {"filename": "native.whl", "url": "https://example.test/native.whl",
                "sha256": hashlib.sha256(payload).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "wheel archive is invalid"):
                verified_artifact(item, directory, opener=lambda *_args, **_kwargs: io.BytesIO(payload))
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_native_distribution_checksum_is_verified_before_installation(self):
        from scripts.native_artifacts import verified_artifact, select_artifact
        manifest = Path(__file__).resolve().parents[2] / "requirements/native-artifacts.json"
        artifact = select_artifact(manifest, "0.3.36", source=True)
        self.assertTrue(artifact["filename"].endswith(".tar.gz"))
        with self.assertRaises(ValueError):
            select_artifact(manifest, "0.0.0", source=True)
        with tempfile.TemporaryDirectory() as directory:
            item = {"filename": "sample.tar.gz", "url": "https://example.test/sample.tar.gz",
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
            requirements.write_text("llama-cpp-python==0.3.36\n", encoding="utf-8")
            manifest = root / "requirements/native-artifacts.json"
            manifest.parent.mkdir()
            manifest.write_bytes(b'{"version":"0.3.36"}\r\n')
            wheels = root / "wheels"
            wheels.mkdir()
            tag = next(sys_tags())
            wheel = wheels / f"llama_cpp_python-0.3.36-{tag}.whl"
            wheel.write_bytes(b"Synthetic native wheel")
            (wheels / "llama_cpp_python-0.3.36-py2-none-any.whl").write_bytes(b"Incompatible wheel")
            with (patch.object(lock_environment, "ROOT", root),
                  patch.object(lock_environment, "dependency_closure", return_value={"llama-cpp-python": "0.3.36"}),
                  patch.object(lock_environment.subprocess, "run", side_effect=AssertionError("unexpected_index_access"))):
                captured = lock_environment.capture_lock(root / "target.lock.json", [requirements], wheels)
                manifest.write_bytes(b'{"version":"0.3.36"}\n')
                verified = lock_environment.verify_lock(root / "target.lock.json", installed={"llama-cpp-python": "0.3.36"})
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
