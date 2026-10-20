"""Catalog synchronization preserves translations and rejects unsupported input."""

from pathlib import Path
import tempfile
import unittest

from scripts.i18n.catalog_tools import read_po_entries, write_po


class CatalogToolsTests(unittest.TestCase):
    def test_sync_preserves_comments_multiline_text_and_current_translations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "ja_JP" / "LC_MESSAGES" / "messages.po"
            path.parent.mkdir(parents=True)
            path.write_text('# Translator note\n#: example.py:12\nmsgid "Save"\n'
                            'msgstr "Saved "\n"translation"\n\nmsgid "Removed"\nmsgstr "Old"\n', encoding="utf-8")
            write_po("ja_JP", {"Save"}, root)
            self.assertEqual(read_po_entries(path)["Save"], "Saved translation")
            self.assertNotIn("Removed", read_po_entries(path))
            content = path.read_text(encoding="utf-8")
            self.assertIn("# Translator note\n#: example.py:12", content)

    def test_unsupported_catalog_entries_are_rejected_before_replacement(self):
        for entry in ('msgid "day"\nmsgid_plural "days"\nmsgstr[0] "day"\n',
                      'msgctxt "button"\nmsgid "Save"\nmsgstr "Save"\n',
                      '#, fuzzy\nmsgid "Save"\nmsgstr "Saved"\n'):
            with self.subTest(entry=entry), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / "ja_JP" / "LC_MESSAGES" / "messages.po"
                path.parent.mkdir(parents=True)
                path.write_text(entry, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Unsupported gettext"):
                    write_po("ja_JP", {"Save"}, root)
                self.assertEqual(path.read_text(encoding="utf-8"), entry)

    def test_duplicate_messages_do_not_silently_replace_translations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "messages.po"
            path.write_text('msgid "Save"\nmsgstr "First"\n\nmsgid "Save"\nmsgstr "Second"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate gettext message"):
                read_po_entries(path)
