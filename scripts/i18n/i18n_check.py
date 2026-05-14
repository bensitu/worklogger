"""Validate gettext extraction and catalog consistency."""

from __future__ import annotations

import ast
from pathlib import Path

from catalog_tools import (
    LANGUAGES,
    LOCALES_ROOT,
    POT_PATH,
    SOURCE_ROOT,
    extract_source_messages,
    read_po_msgids,
)


def _production_python_files() -> list[Path]:
    return [
        path
        for path in SOURCE_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
    ]


def _i18n_api_offenders() -> list[str]:
    offenders: list[str] = []
    for path in _production_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "MSG_DEFAULTS":
                offenders.append(f"{path}: MSG_DEFAULTS")
            elif isinstance(node, ast.FunctionDef) and node.name == "msg":
                offenders.append(f"{path}: def msg")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "msg":
                offenders.append(f"{path}: msg()")
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "msg" or alias.asname == "msg":
                        offenders.append(f"{path}: import msg")
    return offenders


def main() -> int:
    errors: list[str] = []
    source_messages = extract_source_messages()
    pot_messages = read_po_msgids(POT_PATH)
    if source_messages != pot_messages:
        errors.append("messages.pot does not match extracted gettext msgids")

    en_path = LOCALES_ROOT / "en_US" / "LC_MESSAGES" / "messages.po"
    en_messages = read_po_msgids(en_path)
    if en_messages != source_messages:
        errors.append("en_US/messages.po does not match extracted gettext msgids")

    for language in LANGUAGES:
        path = LOCALES_ROOT / language / "LC_MESSAGES" / "messages.po"
        if read_po_msgids(path) != en_messages:
            errors.append(f"{language}/messages.po diverges from en_US msgids")

    offenders = _i18n_api_offenders()
    if offenders:
        errors.extend(offenders)

    if errors:
        for error in errors:
            print(error)
        return 1
    print("i18n check ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

