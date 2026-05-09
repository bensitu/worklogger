import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = PROJECT_ROOT / "worklogger"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


class RequiredInternalImportTests(unittest.TestCase):
    def test_source_imports_required_report_service_modules(self):
        import services.report_service as report_service
        from services.app_services import AppServices

        self.assertTrue(hasattr(report_service, "generate_weekly"))
        self.assertTrue(AppServices)

    def test_pyinstaller_spec_declares_required_service_imports(self):
        spec_path = PROJECT_ROOT / "worklogger.spec"
        spec_text = spec_path.read_text(encoding="utf-8")
        hook_path = (
            PROJECT_ROOT
            / "scripts"
            / "build"
            / "pyinstaller_hooks"
            / "hook-services.py"
        )
        hook_text = hook_path.read_text(encoding="utf-8")

        self.assertIn("REQUIRED_INTERNAL_MODULES", spec_text)
        self.assertIn('"services.report_service"', spec_text)
        self.assertIn("_hiddenimports", spec_text)
        self.assertIn("hookspath=[str(HOOKS_DIR)]", spec_text)
        self.assertIn('collect_submodules("services")', hook_text)
        self.assertTrue(hook_path.is_file())


if __name__ == "__main__":
    unittest.main()
