"""Check repository documentation against local files and the current schema."""

from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRIVATE_DOCUMENTS = {"WORKLOGGER_DEVELOPMENT_RULES.md", "ui_acceptance.md"}
DOCUMENTS = (
    *(PROJECT_ROOT / name for name in (
        "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "SECURITY.md",
        "CODE_OF_CONDUCT.md",
    )),
    *(path for path in sorted((PROJECT_ROOT / "docs").glob("*.md"))
      if path.name not in PRIVATE_DOCUMENTS),
)


class DocumentationTests(unittest.TestCase):
    def test_guides_are_english_and_free_of_machine_specific_paths(self):
        non_english = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
        machine_path = re.compile(r"(?<!\w)[A-Za-z]:[\\/]|[\\/]Users[\\/][^\s/\\]+")
        for path in DOCUMENTS:
            with self.subTest(document=path.name):
                content = path.read_text(encoding="utf-8")
                self.assertIsNone(non_english.search(content))
                self.assertIsNone(machine_path.search(content))

    def test_documentation_index_links_every_public_guide(self):
        index = (PROJECT_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
        for path in DOCUMENTS:
            if path.parent.name == "docs" and path.name != "README.md":
                with self.subTest(document=path.name):
                    self.assertIn(f"]({path.name})", index)

    def test_local_markdown_links_resolve(self):
        for path in DOCUMENTS:
            content = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]\n]+\]\(([^)\n]+)\)", content):
                link = urlsplit(target.strip("<>"))
                if link.scheme or link.netloc or not link.path:
                    continue
                with self.subTest(document=path.name, target=target):
                    self.assertTrue((path.parent / unquote(link.path)).exists())

    def test_python_examples_have_valid_syntax(self):
        for path in DOCUMENTS:
            content = path.read_text(encoding="utf-8")
            for index, source in enumerate(re.findall(r"```python\n(.*?)\n```", content, re.DOTALL)):
                with self.subTest(document=path.name, example=index):
                    compile(source, f"{path.name}:{index}", "exec")

    def test_database_guide_lists_each_current_application_table(self):
        content = (PROJECT_ROOT / "docs" / "database.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(Path(directory) / "worklog.db")
            MigrationRunner(factory).run_pending()
            with factory.connection() as connection:
                names = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name NOT LIKE 'sqlite_%'"
                    )
                }
        documented = set(re.findall(r"^\| `([a-z_]+)` \|", content, re.MULTILINE))
        self.assertEqual(documented, names)


if __name__ == "__main__":
    unittest.main()
