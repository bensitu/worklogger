import locale
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

import utils.i18n as i18n


class I18nPackagingRuntimeTests(unittest.TestCase):
    @staticmethod
    def _sandbox_temp_dir() -> str:
        base = Path(PROJECT_ROOT) / "tests" / "_artifacts"
        base.mkdir(parents=True, exist_ok=True)
        return str(base)

    def _make_case_root(self, prefix: str) -> Path:
        base = Path(self._sandbox_temp_dir()) / "i18n_packaging_cases"
        base.mkdir(parents=True, exist_ok=True)
        root = base / f"{prefix}_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def test_spec_includes_locales_into_bundle_root(self):
        spec_path = Path(PROJECT_ROOT) / "worklogger.spec"
        text = spec_path.read_text(encoding="utf-8")
        self.assertIn('("worklogger/locales",                              "locales")', text)

    def test_diagnostics_reports_readable_catalogs_for_all_languages(self):
        for lang in i18n.LANG_NAMES:
            diag = i18n.get_i18n_diagnostics(lang)
            self.assertTrue(diag["selected_exists"], f"missing locales dir for {lang}: {diag}")
            self.assertTrue(diag["catalog_exists"], f"missing catalog for {lang}: {diag}")
            self.assertTrue(diag["catalog_readable"], f"unreadable catalog for {lang}: {diag}")

    def test_set_language_binds_textdomain_and_attempts_setlocale(self):
        setlocale_calls: list[tuple[int, str]] = []

        def _fake_setlocale(category: int, value: str):
            setlocale_calls.append((category, value))
            if len(setlocale_calls) == 1:
                raise locale.Error("first candidate rejected")
            return value

        with (
            patch("utils.i18n.gettext.bindtextdomain") as mock_bind,
            patch("utils.i18n.gettext.textdomain") as mock_textdomain,
            patch("utils.i18n.locale.setlocale", side_effect=_fake_setlocale),
        ):
            i18n.set_language("ja_JP")

        self.assertGreaterEqual(len(setlocale_calls), 1)
        self.assertTrue(all(cat == locale.LC_ALL for cat, _ in setlocale_calls))
        mock_bind.assert_called_once()
        args = mock_bind.call_args.args
        self.assertEqual(args[0], i18n.DOMAIN)
        self.assertTrue(str(args[1]))
        mock_textdomain.assert_called_once_with(i18n.DOMAIN)

    def test_frozen_meipass_prefers_root_locales_directory(self):
        tmp_root = self._make_case_root("frozen_root_locales")
        bundled = tmp_root / "locales" / "en_US" / "LC_MESSAGES"
        bundled.mkdir(parents=True, exist_ok=True)
        src_mo = Path(APP_ROOT) / "locales" / "en_US" / "LC_MESSAGES" / "messages.mo"
        shutil.copy2(src_mo, bundled / "messages.mo")

        with (
            patch("utils.i18n._DEV_LOCALES_DIR", tmp_root / "missing"),
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_root), create=True),
        ):
            resolved = i18n._resolve_locales_dir("en_US")
        self.assertEqual(resolved, tmp_root / "locales")

    def test_frozen_meipass_compat_worklogger_locales_directory(self):
        tmp_root = self._make_case_root("frozen_worklogger_locales")
        bundled = tmp_root / "worklogger" / "locales" / "en_US" / "LC_MESSAGES"
        bundled.mkdir(parents=True, exist_ok=True)
        src_mo = Path(APP_ROOT) / "locales" / "en_US" / "LC_MESSAGES" / "messages.mo"
        shutil.copy2(src_mo, bundled / "messages.mo")

        with (
            patch("utils.i18n._DEV_LOCALES_DIR", tmp_root / "missing"),
            patch.object(sys, "frozen", True, create=True),
            patch.object(sys, "_MEIPASS", str(tmp_root), create=True),
        ):
            resolved = i18n._resolve_locales_dir("en_US")
        self.assertEqual(resolved, tmp_root / "worklogger" / "locales")


if __name__ == "__main__":
    unittest.main()

