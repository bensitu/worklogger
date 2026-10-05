"""Check repository documentation against local files and the current schema."""

from pathlib import Path
import re
import tempfile
import unittest
from urllib.parse import unquote, urlsplit

from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GUIDES = (
    "README", "architecture", "configuration", "database", "data-formats",
    "development", "integrations", "localization", "packaging", "security",
    "templates", "testing", "troubleshooting", "user-guide", "reliability",
)
DOCUMENTS = (
    *(PROJECT_ROOT / name for name in (
        "README.md", "CONTRIBUTING.md", "CHANGELOG.md", "SECURITY.md",
        "CODE_OF_CONDUCT.md",
    )),
    *(PROJECT_ROOT / "docs" / f"{name}.md" for name in GUIDES),
)


class DocumentationTests(unittest.TestCase):
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
