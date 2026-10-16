from __future__ import annotations

from datetime import date, timedelta
import tempfile
import unittest
from unittest.mock import patch
from worklogger.app.use_cases.notes import DailyNotesService
from worklogger.domain.notes.preferences import NoteSharing, note_draft_key, note_sharing_key
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.quicklog.models import QuickLog
from tests.quick_log_samples import insert_previous_entry
from worklogger.domain.quicklog.rules import quick_log_reference
from worklogger.domain.shared.dates import time_range_label
from worklogger.app.commands.report_commands import GenerateReportCommand
from worklogger.app.use_cases.reports import GenerateReportHandler
from worklogger.infrastructure.repositories import SQLiteCalendarEventRepository
from worklogger.infrastructure.repositories import SQLiteSettingsRepository, SQLiteQuickLogRepository

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
from worklogger.domain.worklog.models import WorkLog
from worklogger.domain.notes.models import DailyNote, NoteHistoryFilter
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.current_schema import CURRENT_SCHEMA_VERSION
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
    def test_note_deletion_is_atomic_scoped_and_preserves_other_records(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/notes.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            owner = auth.create_user("notes.owner", "example-password", recovery_key=None, is_admin=False)
            other = auth.create_user("notes.other", "example-password", recovery_key=None, is_admin=False)
            notes, settings, quick = SQLiteDailyNoteRepository(factory), SQLiteSettingsRepository(factory), SQLiteQuickLogRepository(factory)
            service = DailyNotesService(user_id=owner.id, notes=notes, settings=settings, previous_entries=quick)
            day, another_day = date(2026, 10, 9), date(2026, 10, 8)
            notes.save(DailyNote(owner.id, day, "Saved note"), sharing=NoteSharing(True, False))
            notes.save(DailyNote(other.id, day, "Other account"))
            notes.save(DailyNote(owner.id, another_day, "Other date"))
            entry = insert_previous_entry(factory, QuickLog(None, owner.id, day, "Previous entry"))
            work = SQLiteWorkLogRepository(factory)
            work.save_entry(WorkLog(owner.id, day, "09:00", "10:00", note="Work record"))
            calendar = SQLiteCalendarEventRepository(factory)
            calendar.add_many(owner.id, (CalendarEvent(None, owner.id, day, "Appointment", "10:00", "11:00"),))
            events = calendar.list_for_day(owner.id, day)
            original = service.load(day).value
            service.save_draft(day, "Draft", "Saved note", original.sharing)
            notes.save(DailyNote(owner.id, day, "Changed elsewhere"))
            result = service.delete(day, original.expected_content, original.expected_sharing)
            self.assertEqual(result.error.code, "note_conflict")
            current = service.load(day, recover_draft=False).value
            notes.save(current.note, sharing=NoteSharing())
            result = service.delete(day, current.expected_content, current.expected_sharing)
            self.assertEqual(result.error.code, "note_conflict")
            current = service.load(day, recover_draft=False).value
            with factory.transaction() as connection:
                connection.execute("CREATE TRIGGER protect_preferences BEFORE DELETE ON settings "
                                   "BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END")
            result = service.delete(day, current.expected_content, current.expected_sharing)
            self.assertEqual(result.error.code, "note_delete_failed")
            self.assertEqual(notes.get_for_day(owner.id, day).content, "Changed elsewhere")
            self.assertIsNotNone(settings.get(owner.id, note_draft_key(day)))
            with factory.transaction() as connection:
                connection.execute("DROP TRIGGER protect_preferences")
            result = service.delete(day, current.expected_content, current.expected_sharing)
            self.assertTrue(result.ok, result.error)
            self.assertEqual((result.value.content, result.value.sharing), ("", NoteSharing()))
            self.assertEqual(result.value.previous_entries, (entry,))
            self.assertIsNone(settings.get(owner.id, note_draft_key(day)))
            self.assertIsNone(settings.get(owner.id, note_sharing_key(day)))
            self.assertEqual(notes.get_for_day(owner.id, day).content, "")
            self.assertEqual(notes.get_for_day(other.id, day).content, "Other account")
            self.assertEqual(notes.get_for_day(owner.id, another_day).content, "Other date")
            self.assertEqual(work.get_for_day(owner.id, day).note, "Work record")
            self.assertEqual(calendar.list_for_day(owner.id, day), events)
            self.assertEqual(quick.list_for_day(owner.id, day), (entry,))

    def test_note_history_filters_pages_and_returns_bounded_account_scoped_previews(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/notes.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            owner = auth.create_user("history.owner", "example-password", recovery_key=None, is_admin=False)
            other = auth.create_user("history.other", "example-password", recovery_key=None, is_admin=False)
            notes = SQLiteDailyNoteRepository(factory)
            start = date(2024, 1, 1)
            for offset in range(70):
                content = "Summary\n" + "x" * 10000 + (" Archived reference" if offset == 0 else "")
                notes.save(DailyNote(owner.id, start + timedelta(days=offset), content))
            notes.save(DailyNote(other.id, start + timedelta(days=100), "Private summary"))
            notes.save(DailyNote(owner.id, date(2023, 12, 31), ""))
            legacy_day = date(2023, 12, 30)
            for text in ("100%_complete\\done", "Another previous entry"):
                insert_previous_entry(factory, QuickLog(None, owner.id, legacy_day, text))
            insert_previous_entry(factory, QuickLog(None, owner.id, start, "Matching previous entry"))
            page = notes.browse(owner.id, NoteHistoryFilter())
            self.assertEqual((len(page.notes), page.total), (50, 71))
            self.assertTrue(all(len(note.text) <= 160 and "\n" not in note.text for note in page.notes))
            self.assertNotIn(start, [note.day for note in page.notes])
            archived = notes.browse(owner.id, NoteHistoryFilter(text="Archived reference"))
            self.assertEqual((archived.total, [note.day for note in archived.notes]), (1, [start]))
            matches = notes.browse(owner.id, NoteHistoryFilter(text="Summary"))
            more_matches = notes.browse(owner.id, NoteHistoryFilter(text="Summary", before=matches.next_before))
            self.assertEqual((len(matches.notes), len(more_matches.notes), more_matches.total), (50, 20, 70))
            remaining = notes.browse(owner.id, NoteHistoryFilter(before=page.next_before))
            self.assertEqual((len(remaining.notes), remaining.total, remaining.next_before), (21, 71, None))
            days = [note.day for note in page.notes + remaining.notes]
            self.assertEqual(days, sorted(set(days), reverse=True))
            self.assertEqual(remaining.notes[-1].text, "100%_complete\\done")
            bounded = notes.browse(owner.id, NoteHistoryFilter(date(2024, 2, 1), date(2024, 2, 29)))
            self.assertEqual((len(bounded.notes), bounded.total), (29, 29))
            exact = notes.browse(owner.id, NoteHistoryFilter(start, start, "previous"))
            self.assertEqual([note.day for note in exact.notes], [start])
            escaped = notes.browse(owner.id, NoteHistoryFilter(text="100%_complete\\"))
            self.assertEqual([note.day for note in escaped.notes], [legacy_day])
            self.assertEqual(notes.browse(owner.id, NoteHistoryFilter(text="Private")).total, 0)
            self.assertEqual(notes.browse(owner.id, NoteHistoryFilter(text="missing")).notes, ())

    def test_unreadable_draft_preserves_raw_data_and_loads_saved_note(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/notes.db")
            MigrationRunner(factory).run_pending()
            user = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000)).create_user(
                "draft.owner", "example-password", recovery_key=None, is_admin=False)
            notes, settings = SQLiteDailyNoteRepository(factory), SQLiteSettingsRepository(factory)
            day = date(2026, 10, 9)
            notes.save(DailyNote(user.id, day, "Saved content"))
            service = DailyNotesService(user_id=user.id, notes=notes, settings=settings, previous_entries=SQLiteQuickLogRepository(factory))
            for raw in ('{broken', '{"content":42}', '[]'):
                settings.set(user.id, note_draft_key(day), raw)
                with self.assertLogs("worklogger.app.use_cases.notes", level="WARNING"):
                    result = service.load(day)
                self.assertTrue(result.ok)
                self.assertEqual(result.value.content, "Saved content")
                self.assertTrue(result.value.draft_unavailable)
                self.assertEqual(settings.get(user.id, note_draft_key(day)), raw)

    def test_previous_entry_transfer_is_atomic_and_requires_unchanged_complete_content(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/notes.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            user = auth.create_user("note.owner", "example-password", recovery_key=None, is_admin=False)
            other = auth.create_user("note.other", "example-password", recovery_key=None, is_admin=False)
            notes, settings, quick = SQLiteDailyNoteRepository(factory), SQLiteSettingsRepository(factory), SQLiteQuickLogRepository(factory)
            service = DailyNotesService(user_id=user.id, notes=notes, settings=settings, previous_entries=quick)
            day = date(2026, 10, 9)
            notes.save(DailyNote(user.id, day, "Original note"))
            first = insert_previous_entry(factory, QuickLog(None, user.id, day, "Planning\nPrepare the agenda", "09:00", "10:00"))
            second = insert_previous_entry(factory, QuickLog(None, user.id, day, "Follow up", "10:00", "11:00"))
            unrelated = insert_previous_entry(factory, QuickLog(None, other.id, day, "Private entry"))
            original = service.load(day).value
            content = "Original note\n" + "\n".join(quick_log_reference(entry) for entry in original.previous_entries)
            service.save_draft(day, content, "Original note", NoteSharing(True, False))
            with factory.transaction(write=True) as connection:
                connection.execute("UPDATE quick_logs SET description=? WHERE id=? AND user_id=?",
                                   ("Updated follow up", second.id, user.id))
            rejected = service.save(day, content, original.expected_content, NoteSharing(True, False),
                                    original.expected_sharing, previous_entries_to_remove=original.previous_entries)
            self.assertEqual(rejected.error.code, "note_conflict")
            self.assertEqual(notes.get_for_day(user.id, day).content, "Original note")
            self.assertEqual(len(quick.list_for_day(user.id, day)), 2)
            self.assertIsNotNone(settings.get(user.id, note_draft_key(day)))
            self.assertEqual(service.load(day).value.saved_sharing, NoteSharing())
            missing_content = service.save(day, "Original note", "Original note", NoteSharing(),
                                           previous_entries_to_remove=(first,))
            self.assertEqual(missing_content.error.code, "note_conflict")
            wrong_owner = service.save(day, quick_log_reference(unrelated), "Original note", NoteSharing(),
                                       previous_entries_to_remove=(unrelated,))
            self.assertEqual(wrong_owner.error.code, "note_conflict")
            current = service.load(day, recover_draft=False).value
            merged = "Original note\n" + "\n".join(quick_log_reference(entry) for entry in current.previous_entries)
            notes.save(DailyNote(user.id, day, "Changed elsewhere"))
            stale = service.save(day, merged, current.expected_content, NoteSharing(),
                                 previous_entries_to_remove=current.previous_entries)
            self.assertEqual(stale.error.code, "note_conflict")
            current = service.load(day, recover_draft=False).value
            merged = current.content + "\n" + "\n".join(quick_log_reference(entry) for entry in current.previous_entries)
            saved = service.save(day, merged, current.expected_content, NoteSharing(True, False),
                                 current.expected_sharing, previous_entries_to_remove=current.previous_entries)
            self.assertTrue(saved.ok, saved.error)
            self.assertEqual(saved.value.previous_entries, ())
            self.assertEqual(notes.get_for_day(user.id, day).content, merged)
            self.assertEqual(quick.list_for_day(user.id, day), ())
            self.assertEqual(quick.list_for_day(other.id, day), (unrelated,))
            self.assertIsNone(settings.get(user.id, note_draft_key(day)))
            self.assertEqual(service.load(day).value.sharing, NoteSharing(True, False))

    def test_memo_workspaces_isolate_search_and_commit_sharing_with_content(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/memos.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            user = auth.create_user("memo.owner", "example-password", recovery_key=None, is_admin=False)
            other = auth.create_user("memo.other", "example-password", recovery_key=None, is_admin=False)
            notes, settings, quick = SQLiteDailyNoteRepository(factory), SQLiteSettingsRepository(factory), SQLiteQuickLogRepository(factory)
            service = DailyNotesService(user_id=user.id, notes=notes, settings=settings, previous_entries=quick)
            day = date(2026, 5, 14)
            insert_previous_entry(factory, QuickLog(None, user.id, day, "100% complete", "09:00", "10:00"))
            notes.save(DailyNote(other.id, day, "private 100%"))
            self.assertEqual([note.text for note in service.browse(NoteHistoryFilter(text="100%")).value.notes],
                             ["100% complete"])
            self.assertFalse(service.load(day).value.sharing.reports)
            self.assertTrue(service.save_draft(day, "Draft", "", NoteSharing(True, False)).ok)
            with patch("worklogger.infrastructure.repositories.note_sqlite.note_sharing_key", side_effect=OSError("storage unavailable")):
                self.assertFalse(service.save(day, "Draft", "", NoteSharing(True, False)).ok)
            self.assertEqual(notes.get_for_day(user.id, day).content, "")
            self.assertIsNotNone(settings.get(user.id, note_draft_key(day)))
            self.assertTrue(service.save(day, "Draft", "", NoteSharing(True, False)).ok)
            self.assertIsNone(settings.get(user.id, note_draft_key(day)))
            state = service.load(day).value
            self.assertEqual(state.sharing, NoteSharing(True, False))
            self.assertEqual(state.previous_entries[0].description, "100% complete")
            self.assertFalse(service.save(day, "Stale", "", NoteSharing(False, True)).ok)
            self.assertEqual(service.load(day).value.sharing, NoteSharing(True, False))
            workspace = service.load(day).value
            notes.save(DailyNote(user.id, day, "Draft"), sharing=NoteSharing())
            rejected = service.save(day, "Edited", "Draft", workspace.sharing, workspace.expected_sharing)
            self.assertEqual(rejected.error.code, "note_conflict")
            self.assertEqual(service.load(day).value.sharing, NoteSharing())
            work = SQLiteWorkLogRepository(factory)
            work.save_entry(WorkLog(user.id, day, "08:00", "09:00", note="Planning", work_type=WorkType.MEETING))
            work.save_entry(WorkLog(user.id, day, "10:00", "11:00", note="Practice", work_type=WorkType.TRAINING))
            report = GenerateReportHandler(work_logs=work, notes=notes, note_settings=settings,
                quick_logs=quick, calendar_events=SQLiteCalendarEventRepository(factory), templates=BuiltInTemplateProvider())
            command = GenerateReportCommand(user.id, "daily", day, day)
            private = report.handle(command).value.content
            self.assertNotIn("Draft", private)
            self.assertIn(time_range_label("08:00", "09:00"), private)
            self.assertIn(time_range_label("10:00", "11:00"), private)
            self.assertIn("Meeting", private)
            self.assertIn("Training", private)
            previous = quick.list_for_day(user.id, day)[0]
            notes.save(DailyNote(user.id, day, "Approved memo\n" + quick_log_reference(previous)), sharing=NoteSharing(True, False))
            approved = report.handle(command).value.content
            self.assertIn("Approved memo", approved)
            self.assertEqual(approved.count("100% complete"), 1)
            self.assertNotIn("Quick Logs", approved)
            self.assertNotIn("## Calendar events", approved)

    def test_note_storage_migration_conflicts_deletion_and_export_preserve_content(self):
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(f"{directory}/worklog.db")
            from tests.infrastructure.schema_samples import create_released_database
            _hasher, user_id = create_released_database(factory)
            day = date(2026, 5, 14)
            note_day = date(2026, 5, 15)
            with factory.transaction() as connection:
                connection.execute('INSERT INTO worklog(user_id,d,start,end,"break",note) VALUES(?,?,?,?,?,?)',
                                   (user_id, day.isoformat(), "09:00", "18:00", 1.0, "original"))
                connection.execute('INSERT INTO worklog(user_id,d,"break",note) VALUES(?,?,0,?)',
                                   (user_id, note_day.isoformat(), "standalone"))
            self.assertEqual(MigrationRunner(factory).run_pending(), (CURRENT_SCHEMA_VERSION,))
            user = SQLiteAuthRepository(factory).get_by_id(user_id)
            self.assertEqual(MigrationRunner(factory).run_pending(), ())
            work_logs = SQLiteWorkLogRepository(factory)
            notes = SQLiteDailyNoteRepository(factory)
            self.assertEqual(notes.get_for_day(user.id, note_day).content, "standalone")
            self.assertIsNone(work_logs.get_for_day(user.id, note_day))
            notes.save(DailyNote(user.id, day, "edited"), expected_content="original")
            saved_record = SaveWorkLogHandler(work_logs).handle(SaveWorkLogCommand(
                user.id, day, "08:00", "18:00", 1.0, "edited record", "normal", expected_note="original"))
            self.assertTrue(saved_record.ok, saved_record.error)
            self.assertEqual(work_logs.get_for_day(user.id, day).start_time, "08:00")
            self.assertEqual(work_logs.get_for_day(user.id, day).note, "edited record")
            self.assertEqual(notes.get_for_day(user.id, day).content, "edited")
            rejected = SaveDailyNoteHandler(notes).handle(SaveDailyNoteCommand(
                user.id, day, "other editor", expected_content="original"))
            self.assertFalse(rejected.ok)
            work_logs.remove(user.id, day)
            self.assertEqual(notes.get_for_day(user.id, day).content, "edited")
            exported = work_logs.list_export_rows(user.id)
            self.assertEqual({row.note for row in exported}, {"edited", "standalone"})
            self.assertEqual(work_logs.list_all(user.id), ())
            work_logs.import_many(exported, overwrite=True)
            self.assertEqual(work_logs.list_all(user.id), ())
            self.assertEqual(notes.get_for_day(user.id, note_day).content, "standalone")

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
        self.assertIn("{{year}}-{{month}}", fallback.value or "")
        for language, title in (("en_US", "Daily Report"), ("ja_JP", "日報"),
                                ("ko_KR", "일일 보고서"), ("zh_CN", "日报"), ("zh_TW", "日報")):
            with self.subTest(language=language):
                content = provider.get_template(language, "daily").value
                self.assertIn(title, content)
                self.assertIn("{{notes_section}}", content)
                self.assertNotIn("Quick Logs", content)

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
        self.assertIn("Weekly Report", fallback.value or "")

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
