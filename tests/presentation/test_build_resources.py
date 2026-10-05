from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build import build_environment
from scripts.build_resources import bundled_resources, executable_icon
from scripts.i18n.catalog_tools import compile_po_to_mo, locale_po_paths

ROOT = Path(__file__).resolve().parents[2]


class BuildResourceTests(unittest.TestCase):
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
