from __future__ import annotations

import ast
from pathlib import Path
import unittest


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
    def test_domain_has_no_ui_database_or_infrastructure_imports(self) -> None:
        forbidden = ("PySide6", "sqlite3", "worklogger.infrastructure")
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT / "domain"):
            for module_name in _imports_for(path):
                if module_name.startswith(forbidden):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {module_name}")
        self.assertEqual(offenders, [])

    def test_app_has_no_qt_widget_or_sqlite_imports(self) -> None:
        forbidden = ("PySide6.QtWidgets", "sqlite3")
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

    def test_implementation_names_do_not_use_forbidden_version_terms(self) -> None:
        version_suffix = "v" + "4"
        class_suffix = "V" + "4"
        forbidden = (
            "worklogger_" + version_suffix,
            version_suffix + "_main",
            version_suffix + "-main",
            class_suffix + "App",
            "App" + class_suffix,
            "WorkLogger" + class_suffix,
            "migration_001_" + version_suffix + "_schema",
            "worklog_" + version_suffix,
        )
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                if needle in rel or needle in text:
                    offenders.append(f"{rel}: {needle}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
