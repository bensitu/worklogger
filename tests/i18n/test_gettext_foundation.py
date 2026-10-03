from __future__ import annotations

import ast
import subprocess
import sys
import gettext
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.i18n.catalog_tools import (
    LANGUAGES,
    LOCALES_ROOT,
    POT_PATH,
    SOURCE_ROOT,
    extract_source_messages,
    read_po_msgids,
    read_po_entries,
    compile_po_to_mo,
)
from worklogger.infrastructure.i18n import (
    _,
    available_languages,
    detect_system_language,
    get_language,
    ngettext,
    normalize_language,
    set_language,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class GettextFoundationTests(unittest.TestCase):
    def test_explicit_catalog_does_not_change_active_language(self) -> None:
        set_language("zh_CN")
        self.assertEqual(_("Japanese", language="ja_JP"), "日本語")
        self.assertEqual(get_language(), "zh_CN")
        self.assertEqual(_("Settings"), "设置")

    def test_compiled_catalogs_translate_controls_and_plural_events(self) -> None:
        expected = {"en_US": "Settings", "zh_CN": "设置", "zh_TW": "設定", "ja_JP": "設定", "ko_KR": "설정"}
        with tempfile.TemporaryDirectory() as directory:
            for language in LANGUAGES:
                po_path = LOCALES_ROOT / language / "LC_MESSAGES" / "messages.po"
                entries = read_po_entries(po_path)
                self.assertTrue(all(value.strip() for key, value in entries.items() if key))
                mo = compile_po_to_mo(po_path, Path(directory) / f"{language}.mo")
                with mo.open("rb") as source:
                    translation = gettext.GNUTranslations(source)
                self.assertEqual(translation.gettext("Settings"), expected[language])
                self.assertEqual(translation.ngettext("{count} event", "{count} events", 2), entries["{count} events"])

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

    def test_regional_and_script_language_matching(self) -> None:
        cases = {
            "en-GB": "en_US", "JA_jp.UTF-8": "ja_JP", "ko": "ko_KR",
            "zh": "zh_CN", "zh-SG": "zh_CN", "zh-CN": "zh_CN",
            "zh-TW": "zh_TW", "zh-HK": "zh_TW", "zh-MO": "zh_TW",
            "zh-Hant": "zh_TW", "zh-Hans": "zh_CN",
            "zh-Hant-CN": "zh_TW", "zh-Hans-HK": "zh_CN",
            " ZH_hant_tw ": "zh_TW", "fr-FR": "en_US", "": "en_US",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(normalize_language(value), expected)

    def test_system_ui_preference_order_skips_unsupported_languages(self) -> None:
        for languages, expected in (
            (["fr-FR", "ja-JP", "en-US"], "ja_JP"),
            (["zh-HK", "en-US"], "zh_TW"),
            (["en-GB", "ja-JP"], "en_US"),
            (["de-DE", "fr-FR"], "en_US"),
        ):
            with self.subTest(languages=languages), patch("worklogger.infrastructure.i18n.QLocale") as locale:
                locale.system.return_value.uiLanguages.return_value = languages
                self.assertEqual(detect_system_language(), expected)

    def test_system_locale_name_fallback_and_detection_failure(self) -> None:
        with patch("worklogger.infrastructure.i18n.QLocale") as locale:
            locale.system.return_value.uiLanguages.return_value = []
            locale.system.return_value.name.return_value = "ko_KR"
            self.assertEqual(detect_system_language(), "ko_KR")
            locale.system.side_effect = RuntimeError("unavailable")
            self.assertEqual(detect_system_language(), "en_US")

    def test_untranslated_catalog_entries_never_hide_ui_text(self) -> None:
        for language in LANGUAGES:
            with self.subTest(language=language):
                set_language(language)
                self.assertTrue(_("Welcome!"))
                self.assertTrue(_("Settings"))
                self.assertTrue(ngettext("{count} event", "{count} events", 2))

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
