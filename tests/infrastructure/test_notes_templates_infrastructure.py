from __future__ import annotations

from datetime import date
import tempfile
import unittest

from worklogger.app.commands.auth_commands import RegisterUserCommand
from worklogger.app.commands.note_commands import SaveDailyNoteCommand
from worklogger.app.commands.report_commands import SaveReportTemplateCommand
from worklogger.app.commands.work_log_commands import SaveWorkLogCommand
from worklogger.app.queries.note_queries import GetDailyNoteQuery
from worklogger.app.use_cases.auth import RegisterUserHandler
from worklogger.app.use_cases.notes import GetDailyNoteHandler, SaveDailyNoteHandler
from worklogger.app.use_cases.reports import SaveReportTemplateHandler
from worklogger.app.use_cases.work_logs import SaveWorkLogHandler
from worklogger.domain.worklog.models import WorkType
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.export import MarkdownExporter
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
    SQLiteDailyNoteRepository,
    SQLiteReportTemplateRepository,
    SQLiteWorkLogRepository,
)
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.infrastructure.templates import BuiltInTemplateProvider, UserTemplateProvider


class NotesTemplatesInfrastructureTests(unittest.TestCase):
    def test_sqlite_daily_note_repository_preserves_worklog_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/worklog.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(
                factory,
                password_hasher=PBKDF2PasswordHasher(iterations=1_000),
            )
            registered = RegisterUserHandler(auth).handle(
                RegisterUserCommand("alice", "secret123")
            )
            assert registered.value is not None
            user_id = registered.value.user.id
            work_logs = SQLiteWorkLogRepository(factory)
            SaveWorkLogHandler(work_logs).handle(
                SaveWorkLogCommand(
                    user_id=user_id,
                    day=date(2026, 5, 14),
                    start_time="09:00",
                    end_time="18:00",
                    break_hours=1.0,
                    note="old",
                    work_type=WorkType.REMOTE.value,
                )
            )
            notes = SQLiteDailyNoteRepository(factory)

            saved = SaveDailyNoteHandler(notes).handle(
                SaveDailyNoteCommand(user_id, date(2026, 5, 14), "new note")
            )
            loaded = GetDailyNoteHandler(notes).handle(
                GetDailyNoteQuery(user_id, date(2026, 5, 14))
            )
            work_log = work_logs.get_for_day(user_id, date(2026, 5, 14))

        self.assertTrue(saved.ok, saved.error)
        self.assertTrue(loaded.ok, loaded.error)
        assert loaded.value is not None
        self.assertEqual(loaded.value.content, "new note")
        self.assertIsNotNone(work_log)
        assert work_log is not None
        self.assertEqual(work_log.start_time, "09:00")
        self.assertEqual(work_log.work_type, WorkType.REMOTE)

    def test_builtin_template_provider_returns_locale_or_english_fallback(self) -> None:
        provider = BuiltInTemplateProvider()

        weekly = provider.get_template("ja_JP", "weekly")
        fallback = provider.get_template("unknown", "monthly")

        self.assertTrue(weekly.ok, weekly.error)
        self.assertIn("{{date_range}}", weekly.value or "")
        self.assertTrue(fallback.ok, fallback.error)
        self.assertIn("{{year}}", fallback.value or "")

    def test_sqlite_custom_template_provider_overrides_builtin_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/worklog.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(
                factory,
                password_hasher=PBKDF2PasswordHasher(iterations=1_000),
            )
            registered = RegisterUserHandler(auth).handle(
                RegisterUserCommand("bob", "secret123")
            )
            assert registered.value is not None
            user_id = registered.value.user.id
            repository = SQLiteReportTemplateRepository(factory)
            saved = SaveReportTemplateHandler(repository).handle(
                SaveReportTemplateCommand(
                    user_id=user_id,
                    language="en_US",
                    template_type="weekly",
                    content="# Custom weekly {{date_range}}",
                )
            )
            provider = UserTemplateProvider(repository, BuiltInTemplateProvider())

            custom = provider.get_template("en_US", "weekly", user_id=user_id)
            fallback = provider.get_template("en_US", "weekly", user_id=user_id + 1)

        self.assertTrue(saved.ok, saved.error)
        self.assertTrue(custom.ok, custom.error)
        self.assertEqual(custom.value, "# Custom weekly {{date_range}}")
        self.assertTrue(fallback.ok, fallback.error)
        self.assertIn("Weekly Work Report", fallback.value or "")

    def test_markdown_exporter_writes_utf8_markdown_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = f"{directory}/report"
            result = MarkdownExporter().export_markdown(destination, "# Report\n\nDone")

            self.assertTrue(result.ok, result.error)
            assert result.value is not None
            self.assertEqual(result.value.suffix, ".md")
            self.assertEqual(result.value.read_text(encoding="utf-8"), "# Report\n\nDone")


if __name__ == "__main__":
    unittest.main()
