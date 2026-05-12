import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
THEME_MODULE = PROJECT_ROOT / "worklogger" / "config" / "themes.py"
EXCLUDED_DIRS = {
    ".git",
    ".ruff_cache",
    ".venv_build",
    "__pycache__",
    "build",
    "dist",
}


class ThemeQssContractTests(unittest.TestCase):
    def test_qss_application_is_centralized_in_themes_module(self):
        needles = ("set" + "Style" + "Sheet", "style" + "Sheet")
        offenders: list[str] = []
        for path in PROJECT_ROOT.rglob("*.py"):
            if any(part in EXCLUDED_DIRS for part in path.parts):
                continue
            if path == THEME_MODULE:
                continue
            text = path.read_text(encoding="utf-8")
            if any(needle in text for needle in needles):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))

        self.assertEqual(offenders, [])

    def test_gitignore_keeps_tests_uploadable(self):
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        ignored_lines = {
            line.strip()
            for line in gitignore.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }

        self.assertNotIn("tests/", ignored_lines)
        self.assertIn("tests/_artifacts/", ignored_lines)


if __name__ == "__main__":
    unittest.main()

