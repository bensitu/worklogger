from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
import unittest

from scripts.i18n.catalog_tools import (
    LANGUAGES,
    LOCALES_ROOT,
    POT_PATH,
    SOURCE_ROOT,
    extract_source_messages,
    read_po_msgids,
)
from worklogger.infrastructure.i18n import (
    _,
    available_languages,
    get_language,
    ngettext,
    set_language,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GettextFoundationTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_language("en_US")

    def test_runtime_uses_gettext_fallback_without_msg_api(self) -> None:
        self.assertEqual(set_language("en_US"), "en_US")
        self.assertEqual(get_language(), "en_US")
        self.assertEqual(_("WorkLogger command line"), "WorkLogger command line")
        self.assertEqual(ngettext("{count} day", "{count} days", 1), "{count} day")
        self.assertEqual(ngettext("{count} day", "{count} days", 2), "{count} days")

    def test_supported_language_normalization(self) -> None:
        self.assertEqual(set_language("ja-JP"), "ja_JP")
        self.assertEqual(set_language("unknown"), "en_US")
        self.assertEqual(available_languages(), tuple(LANGUAGES))

    def test_no_msg_api_or_msg_defaults_in_production_code(self) -> None:
        offenders: list[str] = []
        for path in SOURCE_ROOT.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "MSG_DEFAULTS":
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: MSG_DEFAULTS")
                elif isinstance(node, ast.FunctionDef) and node.name == "msg":
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: def msg")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "msg":
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: msg()")
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == "msg" or alias.asname == "msg":
                            offenders.append(f"{path.relative_to(PROJECT_ROOT)}: import msg")
        self.assertEqual(offenders, [])

    def test_gettext_extraction_matches_pot_and_english_catalog(self) -> None:
        source_messages = extract_source_messages()
        self.assertTrue(source_messages)
        self.assertEqual(read_po_msgids(POT_PATH), source_messages)
        en_path = LOCALES_ROOT / "en_US" / "LC_MESSAGES" / "messages.po"
        self.assertEqual(read_po_msgids(en_path), source_messages)

    def test_language_catalog_msgids_match_en_us(self) -> None:
        en_path = LOCALES_ROOT / "en_US" / "LC_MESSAGES" / "messages.po"
        expected = read_po_msgids(en_path)
        for language in LANGUAGES:
            with self.subTest(language=language):
                path = LOCALES_ROOT / language / "LC_MESSAGES" / "messages.po"
                self.assertEqual(read_po_msgids(path), expected)

    def test_i18n_check_script_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/i18n/i18n_check.py"],
            cwd=PROJECT_ROOT,
            check=False,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
