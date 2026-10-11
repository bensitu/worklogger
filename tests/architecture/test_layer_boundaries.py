from __future__ import annotations

import ast
from pathlib import Path
import unittest
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "worklogger"


def _python_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _imports_for(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


class LayerBoundaryTests(unittest.TestCase):
    def test_theme_color_and_stylesheet_resolution_runs_without_qt(self):
        script = """
import sys
from worklogger.config.themes import THEME_KEYS
from worklogger.presentation.theme import ThemeEngine
engine = ThemeEngine()
for theme in THEME_KEYS:
    for dark in (False, True):
        assert '{{' not in engine.application_stylesheet(theme, dark=dark)
        assert engine.calendar_cell_style({'holiday'}, theme=theme, dark=dark).background
assert not any(name.startswith('PySide6') for name in sys.modules)
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=PROJECT_ROOT,
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_editing_and_settings_viewmodels_import_without_qt(self):
        result = subprocess.run([sys.executable, "-c", "import sys; from worklogger.presentation.viewmodels import TimeEntryViewModel, NoteEditorViewModel, SettingsViewModel; assert not any(name.startswith('PySide6') for name in sys.modules)"],
                                cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_domain_has_no_ui_database_or_infrastructure_imports(self) -> None:
        forbidden = ("PySide6", "sqlite3", "worklogger.infrastructure")
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT / "domain"):
            for module_name in _imports_for(path):
                if module_name.startswith(forbidden):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module_name}")
        self.assertEqual(offenders, [])

    def test_app_has_no_qt_widget_or_sqlite_imports(self) -> None:
        forbidden = ("PySide6", "sqlite3", "worklogger.infrastructure", "worklogger.presentation")
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT / "app"):
            for module_name in _imports_for(path):
                if module_name.startswith(forbidden):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module_name}")
        self.assertEqual(offenders, [])

    def test_presentation_does_not_import_sqlite(self) -> None:
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT / "presentation"):
            for module_name in _imports_for(path):
                if module_name == "sqlite3" or module_name.startswith("sqlite3."):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module_name}")
        self.assertEqual(offenders, [])

    def test_stylesheets_are_applied_only_at_application_boundary(self) -> None:
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT / "presentation"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setStyleSheet"
                ):
                    continue
                target = node.func.value
                if isinstance(target, ast.Name) and target.id == "application":
                    continue
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
