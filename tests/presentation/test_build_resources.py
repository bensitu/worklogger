from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build import build_environment
from scripts.build_resources import bundled_resources, executable_icon
from scripts.i18n.catalog_tools import compile_po_to_mo, locale_po_paths

ROOT = Path(__file__).resolve().parents[2]


class BuildResourceTests(unittest.TestCase):
    def test_locked_environment_rejects_target_input_and_package_mismatches(self):
        import json
        from scripts.lock_environment import verify_lock, digest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "requirements.txt"
            dependency.write_text("sample==1.0\n", encoding="utf-8")
            target = {"system": "Windows", "machine": "AMD64", "python": "3.11.9", "implementation": "CPython"}
            value = {"format_version": 1, "target": target, "inputs": {"requirements.txt": digest(dependency)},
                     "packages": [{"name": "sample", "version": "1.0", "sha256": "a" * 64, "wheel": "sample.whl"}]}
            path = root / "lock.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            with patch("scripts.lock_environment.ROOT", root):
                self.assertEqual(verify_lock(path, installed={"sample": "1.0"}, current_target=target), value)
                for installed, platform in (({"sample": "2.0"}, target), ({"sample": "1.0", "unrelated": "1"}, target),
                                             ({"sample": "1.0"}, dict(target, system="Linux"))):
                    with self.assertRaises(ValueError):
                        verify_lock(path, installed=installed, current_target=platform)
                dependency.write_text("sample==2.0\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_lock(path, installed={"sample": "1.0"}, current_target=target)

    def test_artifact_inventory_refuses_private_runtime_files(self):
        from scripts.release_artifact import artifact_files
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "WorkLogger.exe").write_bytes(b"Synthetic executable")
            self.assertEqual(len(artifact_files(root)), 1)
            for filename in ("worklog.db", "worklog.db-wal", "weights.gguf", "identity.local.json", "session.json"):
                path = root / filename
                path.write_bytes(b"Synthetic private data")
                with self.assertRaises(ValueError):
                    artifact_files(root)
                path.unlink()
    def test_windows_build_excludes_unrelated_tool_dll_paths(self):
        with patch("scripts.build.sys.platform", "win32"), patch.dict(
            "os.environ", {"PATH": r"C:\tools\poppler", "SystemRoot": r"C:\Windows"}
        ):
            environment = build_environment(True)
        self.assertNotIn("poppler", environment["PATH"])
        self.assertIn("System32", environment["PATH"])
        self.assertEqual(environment["WORKLOGGER_BUILD_CONSOLE"], "1")
        self.assertEqual(environment["WORKLOGGER_BUILD_LOCAL_INFERENCE"], "0")
        self.assertEqual(build_environment(False, True)["WORKLOGGER_BUILD_LOCAL_INFERENCE"], "1")

    def test_resource_manifest_contains_fonts_icons_qss_and_catalogs_without_user_data(self):
        for po in locale_po_paths():
            compile_po_to_mo(po)
        resources = bundled_resources(ROOT)
        paths = {Path(source).relative_to(ROOT).as_posix() for source, _ in resources}
        self.assertIn("worklogger/assets/images/worklogger_login_image.webp", paths)
        self.assertIn("worklogger/assets/icons/ui/LICENSE", paths)
        self.assertIn("worklogger/assets/icons/ui/pencil.svg", paths)
        self.assertIn("worklogger/assets/icons/ui/x.svg", paths)
        self.assertIn("worklogger/presentation/theme/qss/blue_dark.qss", paths)
        self.assertEqual(sum(path.endswith(".otf") for path in paths), 5)
        self.assertEqual(sum(path.endswith(".mo") for path in paths), 5)
        self.assertFalse(any(path.endswith((".avif", ".db", ".gguf")) for path in paths))
        self.assertEqual({path for path in paths if path.endswith(".json")}, {"model_catalog.json"})
        self.assertIn((str(ROOT / "model_catalog.json"), "worklogger/assets/models"), resources)
        for platform, suffix in (("win32", ".ico"), ("darwin", ".icns")):
            icon = executable_icon(ROOT, platform)
            self.assertTrue(Path(icon).is_file())
            self.assertTrue(icon.endswith(suffix))
        self.assertIsNone(executable_icon(ROOT, "linux"))

    def test_missing_catalog_stops_build(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                bundled_resources(Path(directory))
