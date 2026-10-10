"""Profile changes preserve authentication, ownership, and saved content."""

from datetime import date
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from worklogger.app.commands.ai_commands import RewriteTextCommand, SendAiChatMessageCommand
from worklogger.app.commands.auth_commands import RegisterUserCommand
from worklogger.app.commands.report_commands import GenerateReportCommand, SaveReportCommand
from worklogger.app.ports import AIResponse
from worklogger.app.use_cases.ai import AiChatHandler, RewriteTextHandler
from worklogger.app.use_cases.auth import RegisterUserHandler
from worklogger.app.use_cases.reports import GenerateReportHandler, SaveReportHandler
from worklogger.app.use_cases.user_profile import UserProfileService
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MIGRATION_MODULES
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteReportRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class UserProfileTests(unittest.TestCase):
    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.directory) / "worklog.db"
        self.factory = SQLiteConnectionFactory(self.path)
        MigrationRunner(self.factory, migration_modules=MIGRATION_MODULES[:9]).run_pending()
        self.auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.registered = RegisterUserHandler(self.auth).handle(RegisterUserCommand("han_meimei", "synthetic-password")).value
        self.other = RegisterUserHandler(self.auth).handle(RegisterUserCommand("other_login", "other-password")).value.user
        with self.factory.connection() as connection:
            self.previous_users = [dict(row) for row in connection.execute("SELECT * FROM users ORDER BY id")]
        self.assertEqual(MigrationRunner(self.factory).run_pending(), tuple(range(10, len(MIGRATION_MODULES) + 1)))
        self.profile = UserProfileService(user_id=self.registered.user.id, repository=self.auth)

    def test_migration_and_profile_changes_preserve_credentials_and_ownership(self):
        with self.factory.connection() as connection:
            original = dict(connection.execute("SELECT * FROM users WHERE id=?", (self.registered.user.id,)).fetchone())
        self.assertEqual(self.profile.load().value.effective_display_name, "han_meimei")
        changed = self.profile.save_display_name("  Mary  ", expected_display_name="")
        self.assertTrue(changed.ok, changed.error)
        self.assertEqual(changed.value.effective_display_name, "Mary")
        with self.factory.connection() as connection:
            updated = dict(connection.execute("SELECT * FROM users WHERE id=?", (self.registered.user.id,)).fetchone())
        expected = dict(original, display_name="Mary")
        self.assertEqual(updated, expected)
        self.assertIsNotNone(self.auth.verify_user("han_meimei", "synthetic-password"))
        self.assertIsNone(self.auth.verify_user("Mary", "synthetic-password"))
        self.assertEqual(self.auth.get_by_id(self.other.id).display_name, "")
        other_profile = UserProfileService(user_id=self.other.id, repository=self.auth)
        self.assertTrue(other_profile.save_display_name("Mary", expected_display_name="").ok)
        self.assertEqual(self.auth.get_by_id(self.other.id).username, "other_login")
        conflict = self.profile.save_display_name("Overwrite", expected_display_name="")
        self.assertEqual(conflict.error.code, "user_profile_conflict")
        for name in ("x" * 81, "Two\nlines", "Spoof\u202ename", "Hidden\x00name", None):
            self.assertFalse(self.profile.save_display_name(name, expected_display_name="Mary").ok)
            self.assertEqual(self.profile.load().value.display_name, "Mary")
        self.assertTrue(self.profile.save_display_name("\u97d3 \u6885\u6885", expected_display_name="Mary").ok)
        cleared = self.profile.save_display_name(" ", expected_display_name="\u97d3 \u6885\u6885")
        self.assertEqual(cleared.value.effective_display_name, "han_meimei")
        self.assertEqual(MigrationRunner(self.factory).run_pending(), ())

    def test_ai_requests_and_new_reports_read_current_name_without_rewriting_history(self):
        gateway = Mock()
        gateway.generate.return_value = Result.success(AIResponse("Reviewed text", "synthetic"))
        rewrite = RewriteTextHandler(gateway, profiles=self.auth)
        chat = AiChatHandler(gateway, profiles=self.auth)
        source = "Han Meimei prepared the original document."
        self.profile.save_display_name("Mary", expected_display_name="")
        rewrite.handle(RewriteTextCommand(self.registered.user.id, source))
        request = gateway.generate.call_args.args[0]
        self.assertIn(json.dumps("Mary"), request.messages[0]["content"])
        self.assertNotIn("han_meimei", request.messages[0]["content"])
        self.assertIn(source, request.messages[1]["content"])
        self.assertIn("Preserve names in source text", request.messages[0]["content"])
        history = ({"role": "assistant", "content": "Hello, Mary."},)
        records = Mock(list_range=Mock(return_value=()))
        quick = Mock(list_for_range=Mock(return_value=()))
        events = Mock(list_for_range=Mock(return_value=()))
        templates = SimpleNamespace(get_template=lambda *args, **kwargs: Result.success("{{display_name}}: {{date}}"))
        generate = GenerateReportHandler(work_logs=records, quick_logs=quick, calendar_events=events,
                                         templates=templates, profiles=self.auth)
        day = date(2026, 10, 10)
        command = GenerateReportCommand(self.registered.user.id, "daily", day, day)
        content = generate.handle(command).value.content
        reports = SQLiteReportRepository(self.factory)
        saved = SaveReportHandler(reports).handle(SaveReportCommand(self.registered.user.id, "daily", day, day, content)).value
        self.profile.save_display_name("Jane", expected_display_name="Mary")
        chat.handle(SendAiChatMessageCommand(user_id=self.registered.user.id, message="Hello", history=history))
        request = gateway.generate.call_args.args[0]
        self.assertIn(json.dumps("Jane"), request.messages[0]["content"])
        self.assertEqual(request.messages[1], history[0])
        self.assertTrue(generate.handle(command).value.content.startswith("Jane:"))
        self.assertEqual(reports.list_by_type(self.registered.user.id, "daily")[0].content, saved.content)
        self.assertTrue(saved.content.startswith("Mary:"))

    def test_profile_migration_adds_only_the_name_and_retains_existing_values(self):
        from worklogger.infrastructure.database.migrations.migration_010_user_display_names import up
        with self.factory.connection() as connection:
            users = [dict(row) for row in connection.execute("SELECT * FROM users ORDER BY id")]
        for previous, current in zip(self.previous_users, users):
            self.assertEqual(current.pop("display_name"), "")
            self.assertEqual(current, previous)
        with self.factory.transaction() as connection:
            connection.execute("UPDATE users SET display_name='Mary' WHERE id=?", (self.registered.user.id,))
            up(connection)
            self.assertEqual(connection.execute("SELECT display_name FROM users WHERE id=?", (self.registered.user.id,)).fetchone()[0], "Mary")
        self.assertTrue(list(self.path.parent.glob(self.path.name + ".bak_upgrade_*")))
