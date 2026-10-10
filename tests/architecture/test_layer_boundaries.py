from __future__ import annotations

import ast
from pathlib import Path
import re
import unittest
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "worklogger"
TESTS_ROOT = PROJECT_ROOT / "tests"
SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
OBJECT_NAME_SUFFIXES = (
    "_button",
    "_check",
    "_combo",
    "_dialog",
    "_double_spin_box",
    "_spin_box",
    "_frame",
    "_label",
    "_line_edit",
    "_list_widget",
    "_panel_widget",
    "_progress_bar",
    "_splitter",
    "_tab_widget",
    "_table_view",
    "_text_edit",
    "_tree_view",
    "_view",
    "_widget",
    "_window",
)
FORBIDDEN_OBJECT_NAME_PARTS = ("_btn", "_input", "muted")


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

    def test_widgets_depend_on_viewmodel_operations_not_business_services(self):
        offenders = []
        for path in _python_files(PACKAGE_ROOT / "presentation" / "widgets"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr == "service":
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [])

    def test_runtime_identifiers_do_not_embed_release_numbers(self) -> None:
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    if re.search(r"[vV]\d+(?:_|$|[A-Z])", node.name):
                        offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {node.name}")
        self.assertEqual(offenders, [])

    def test_runtime_module_names_do_not_embed_release_numbers(self) -> None:
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if re.search(r"(?:^|[/_])[vV]\d+(?:[/_.]|$)", rel):
                offenders.append(rel)
        self.assertEqual(offenders, [])

    def test_test_module_names_use_descriptive_words(self) -> None:
        offenders = [
            path.relative_to(PROJECT_ROOT).as_posix()
            for path in TESTS_ROOT.rglob("test_*.py")
            if not re.fullmatch(r"test_[a-z]+(?:_[a-z]+)*", path.stem)
        ]
        self.assertEqual(offenders, [])

    def test_layer_file_naming_conventions(self) -> None:
        offenders: list[str] = []
        for path in (PACKAGE_ROOT / "app" / "commands").glob("*.py"):
            if path.name != "__init__.py" and not path.name.endswith("_commands.py"):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        for path in (PACKAGE_ROOT / "app" / "queries").glob("*.py"):
            if path.name != "__init__.py" and not path.name.endswith("_queries.py"):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        for path in (PACKAGE_ROOT / "infrastructure" / "repositories").glob("*.py"):
            if path.name not in {"__init__.py", "_mapping.py"} and not path.name.endswith("_sqlite.py"):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        for path in (PACKAGE_ROOT / "presentation").glob("*/*.py"):
            parent = path.parent.name
            if parent in {"shell", "theme", "viewmodels", "widgets"} or path.name == "__init__.py":
                continue
            if path.name not in {"controller.py", "dialog.py", "dialogs.py", "page.py"}:
                offenders.append(str(path.relative_to(PROJECT_ROOT)))
        self.assertEqual(offenders, [])

    def test_command_query_and_viewmodel_class_naming(self) -> None:
        offenders: list[str] = []
        for path in (PACKAGE_ROOT / "app" / "commands").glob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and not node.name.endswith("Command"):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {node.name}")
        for path in (PACKAGE_ROOT / "app" / "queries").glob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and not node.name.endswith("Query"):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {node.name}")
        for path in (PACKAGE_ROOT / "presentation" / "viewmodels").glob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            has_view_model = any(
                isinstance(node, ast.ClassDef) and node.name.endswith("ViewModel")
                for node in tree.body
            )
            if not has_view_model:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: missing ViewModel")
        self.assertEqual(offenders, [])

    def test_qt_object_names_are_descriptive_snake_case(self) -> None:
        offenders: list[str] = []
        for path in _python_files(PACKAGE_ROOT / "presentation"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "setObjectName"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                ):
                    continue
                object_name = node.args[0].value
                if not SNAKE_CASE_RE.match(object_name):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {object_name}")
                    continue
                if any(part in object_name for part in FORBIDDEN_OBJECT_NAME_PARTS):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {object_name}")
                    continue
                if not object_name.endswith(OBJECT_NAME_SUFFIXES):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno}: {object_name}")
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
