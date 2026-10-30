from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from worklogger.app.use_cases.time_entries import TimeEntryService
from worklogger.domain.worklog.timer_state import EntryTimer, encode_timer
from worklogger.app.use_cases.entry_types import EntryTypeService
from worklogger.app.use_cases.work_modes import WorkModeService
from worklogger.infrastructure.repositories.entry_type_sqlite import SQLiteEntryTypeRepository, SQLiteWorkModeRepository
from worklogger.app.use_cases.data_portability import ImportWorkLogsCsvHandler
from worklogger.app.commands.data_portability_commands import ImportWorkLogsCsvCommand
from worklogger.domain.notes.models import DailyNote
from worklogger.domain.analytics.rules import dashboard_data
from worklogger.domain.worklog.models import WorkLog, EntryType, WorkMode
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.database.migrations.runner import MigrationRunner
from worklogger.infrastructure.repositories.auth_sqlite import SQLiteAuthRepository
from worklogger.infrastructure.repositories.settings_sqlite import SQLiteSettingsRepository
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository
from worklogger.infrastructure.repositories.entry_write_session_sqlite import EntryWriteSession
from worklogger.infrastructure.repositories.note_sqlite import SQLiteDailyNoteRepository
from worklogger.infrastructure.export.worklog_csv import WorkLogCsvExporter
from worklogger.infrastructure.export.worklog_csv_import import WorkLogCsvImporter
from worklogger.infrastructure.export.worklog_ics import WorkLogIcsExporter
from worklogger.infrastructure.security.password_hasher import PBKDF2PasswordHasher


class TimeEntryTests(unittest.TestCase):
    def test_failed_timer_end_preserves_recording_for_explicit_recovery(self):
        self.assertTrue(self.service.start("normal", "Ongoing").ok)
        original = self.make_service().timer
        for end in (self.now.replace(tzinfo=None), self.now + timedelta(hours=17)):
            with self.subTest(end=end):
                result = self.service.finish("Completed", now=end)
                self.assertEqual(result.error.code, "time_range_invalid")
                self.assertEqual(self.make_service().timer, original)
                self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        result = self.service.finish("Completed", now=self.now + timedelta(hours=8))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.value.worked_hours(), 8)
        self.assertIsNone(self.make_service().timer)

    def test_explicit_splits_preserve_selected_offsets_after_sqlite_round_trip(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("America/New_York")
        cases = (("2026-03-08T01:30:00-05:00", "2026-03-08T04:30:00-04:00",
                  datetime(2026, 3, 8, 3, 15, 22, 123456, tzinfo=zone)),
                 ("2026-11-01T00:30:00-04:00", "2026-11-01T03:30:00-05:00",
                  datetime(2026, 11, 1, 1, 45, tzinfo=zone, fold=1)))
        for start_text, end_text, cut in cases:
            with self.subTest(cut=cut.isoformat()):
                start, end = datetime.fromisoformat(start_text), datetime.fromisoformat(end_text)
                saved = self.repository.save_entry(WorkLog(self.user.id, start.date(), start.strftime("%H:%M"),
                    end.strftime("%H:%M"), note="Recorded work", entry_type=EntryType.MEETING,
                    started_at=start, ended_at=end, work_mode=WorkMode.REMOTE))
                reopened = SQLiteWorkLogRepository(self.factory)
                original = reopened.get_entry(self.user.id, saved.id)
                result = self.service.split_at(original, cut)
                self.assertTrue(result.ok, result.error)
                left, right = (reopened.get_entry(self.user.id, entry.id) for entry in result.value)
                self.assertEqual((left.ended_at.isoformat(), right.started_at.isoformat()),
                                 (cut.isoformat(), cut.isoformat()))
                self.assertEqual((left.started_at.isoformat(), right.ended_at.isoformat()), (start_text, end_text))
                self.assertEqual((left.end_time, right.start_time), (cut.strftime("%H:%M"),) * 2)
                self.assertAlmostEqual(left.worked_hours() + right.worked_hours(), original.worked_hours())
                for entry in (left, right):
                    self.assertEqual((entry.note, entry.entry_type, entry.work_mode, entry.context),
                                     (original.note, original.entry_type, original.work_mode, original.context))
                self.assertTrue(self.service.undo(self.service.latest_change().value.id).ok)
                restored = reopened.get_entry(self.user.id, saved.id)
                self.assertEqual((restored.started_at.isoformat(), restored.ended_at.isoformat()), (start_text, end_text))

    def test_completed_content_saves_reject_foreign_records_without_changing_timer_behavior(self):
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        other = auth.create_user("other-content-owner", "example-password", recovery_key=None, is_admin=False)
        foreign = self.repository.save_entry(WorkLog(other.id, self.now.date(), "09:00", "10:00", note="Other account"))
        previous_change = self.repository.latest_change(other.id)
        with patch.object(self.repository, "save_entry", wraps=self.repository.save_entry) as save:
            result = self.service.save_content("Invalid edit", foreign)
            self.assertFalse(result.ok)
            self.assertEqual(result.error.code, "worklog_entry_conflict")
            save.assert_not_called()
        self.assertEqual(self.repository.get_entry(other.id, foreign.id), foreign)
        self.assertEqual(self.repository.latest_change(other.id), previous_change)

        self.assertTrue(self.service.start("normal", "Active").ok)
        result = self.service.save_content("Updated timer", foreign)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.make_service().timer.content, "Updated timer")
        self.assertEqual(self.repository.get_entry(other.id, foreign.id), foreign)
        self.assertEqual(self.repository.latest_change(other.id), previous_change)

    def test_custom_search_pages_preserve_cursors_and_find_records_outside_the_first_page(self):
        from dataclasses import replace
        from datetime import date
        from worklogger.domain.worklog.search import EntryFilter

        for offset in range(5):
            saved = self.service.save_manual(self.now.date() + timedelta(days=offset), "07:00", "08:00",
                                             "normal", "Older matching content" if offset == 0 else "Other content")
            self.assertTrue(saved.ok, saved.error)
        service = TimeEntryService(user_id=self.user.id, repository=self.repository, settings=self.settings,
                                   local_timezone=timezone.utc, search_page_size=2)
        session = service.new_session(service.snapshot_state())
        criteria = EntryFilter(date.min, date.max)
        first = service.search(criteria).value
        second = session.search(criteria, cursor=first.next_cursor).value
        third = session.search(criteria, cursor=second.next_cursor).value
        self.assertEqual([len(page.entries) for page in (first, second, third)], [2, 2, 1])
        self.assertEqual(len({entry.id for page in (first, second, third) for entry in page.entries}), 5)
        self.assertIsNone(third.next_cursor)
        found = service.search(replace(criteria, text="Older matching")).value
        self.assertEqual([entry.day for entry in found.entries], [self.now.date()])

    def test_work_arrangement_defaults_change_only_with_successful_new_work(self):
        from dataclasses import replace

        day = self.now.date()
        self.assertIsNone(self.service.default_work_mode())
        saved = self.service.save_manual(day, "06:00", "07:00", "meeting", "Planning", work_mode=WorkMode.REMOTE).value
        self.assertEqual(self.service.default_work_mode(), WorkMode.REMOTE)
        edited = self.service.save_manual(day, "06:00", "07:00", "meeting", "Edited", saved, work_mode=WorkMode.ONSITE).value
        self.assertEqual(self.repository.get_entry(self.user.id, saved.id).work_mode, WorkMode.ONSITE)
        self.assertEqual(self.service.default_work_mode(), WorkMode.REMOTE)
        overlap = self.service.save_manual(day, "06:30", "07:30", "training", "Overlap", work_mode=WorkMode.BUSINESS_TRIP)
        self.assertFalse(overlap.ok)
        self.assertEqual(self.service.default_work_mode(), WorkMode.REMOTE)
        self.assertTrue(self.service.save_manual(day, "07:00", "08:00", "break", "Rest").ok)
        self.assertTrue(self.service.save_manual(day, "08:00", "09:00", "paid_leave", "Leave").ok)
        self.assertEqual(self.service.default_work_mode(), WorkMode.REMOTE)
        self.assertTrue(self.service.start("training", "Practice", work_mode=WorkMode.BUSINESS_TRIP).ok)
        self.assertEqual(self.service.default_work_mode(), WorkMode.REMOTE)
        restored = self.make_service()
        self.assertEqual(restored.timer.work_mode, WorkMode.BUSINESS_TRIP)
        self.assertTrue(restored.finish("Practice", now=self.now + timedelta(hours=1)).ok)
        self.assertEqual(restored.default_work_mode(), WorkMode.BUSINESS_TRIP)
        self.repository.import_many((replace(edited, day=day + timedelta(days=2), id=None, revision=0,
                                             started_at=None, ended_at=None, work_mode=WorkMode.REMOTE),))
        self.assertEqual(restored.default_work_mode(), WorkMode.BUSINESS_TRIP)
        self.assertTrue(restored.save_manual(day, "11:00", "12:00", "normal", "Unspecified", work_mode=None).ok)
        self.assertIsNone(restored.default_work_mode())
        other = TimeEntryService(user_id=self.user.id + 1, repository=self.repository, settings=self.settings,
                                 local_timezone=timezone.utc)
        self.assertIsNone(other.default_work_mode())

    def test_failed_arrangement_persistence_rolls_back_the_record_and_timer(self):
        self.assertTrue(self.service.save_manual(self.now.date(), "07:00", "08:00", "normal", "Earlier", work_mode=WorkMode.REMOTE).ok)
        before = self.repository.list_for_day(self.user.id, self.now.date())
        with patch.object(EntryWriteSession, "remember_work_mode", side_effect=OSError("storage unavailable")):
            self.assertFalse(self.service.save_manual(self.now.date(), "08:00", "09:00", "normal", "New", work_mode=WorkMode.ONSITE).ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), before)
        self.assertEqual(self.service.default_work_mode(), WorkMode.REMOTE)
        for definition in ("paid_leave", self.service.entry_types.save("Personal leave", "leave").value.value):
            self.assertEqual(self.service.start(definition, "Invalid").error.code, "auto_record_leave_not_supported")
        self.assertTrue(self.service.start("meeting", "Work", work_mode=WorkMode.ONSITE).ok)
        with patch.object(EntryWriteSession, "remember_work_mode", side_effect=OSError("storage unavailable")):
            self.assertFalse(self.service.finish("Work", now=self.now + timedelta(hours=1)).ok)
        self.assertEqual(self.make_service().timer.work_mode, WorkMode.ONSITE)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), before)
        self.assertEqual(self.service.default_work_mode(), WorkMode.REMOTE)

    def test_break_timers_restore_and_finish_across_midnight_without_work_metadata(self):
        from worklogger.domain.projects.models import WorkContext

        self.assertTrue(self.service.save_manual(self.now.date(), "07:00", "08:00", "normal", "Work", work_mode=WorkMode.REMOTE).ok)
        custom = self.service.entry_types.save("Personal rest", "break").value
        for definition in (EntryType.BREAK, custom):
            with self.subTest(entry_type=definition.value):
                service = self.make_service()
                self.now = (self.now + timedelta(days=1)).replace(hour=23, minute=40)
                for options in ({"work_mode": WorkMode.REMOTE}, {"context": WorkContext(project_label="Previous project")}):
                    self.assertEqual(service.start(definition.value, "Rest", **options).error.code, "entry_classification_invalid")
                    self.assertIsNone(service.timer)
                self.assertTrue(service.validate_selection(definition.value, None, WorkContext(), automatic=True).ok)
                self.assertTrue(service.start(definition.value, "Rest").ok)
                restored = self.make_service()
                self.assertFalse(restored.restore_failed)
                self.assertEqual(restored.timer.entry_type, definition)
                self.assertIsNone(restored.timer.break_until)
                self.assertTrue(restored.advance().ok)
                self.assertIsNotNone(restored.timer)
                finished = restored.finish("Rest", now=self.now + timedelta(minutes=45))
                self.assertTrue(finished.ok, finished.error)
                record = self.repository.get_entry(self.user.id, finished.value.id)
                self.assertEqual((record.start_time, record.end_time, record.raw_hours(), record.worked_hours()),
                                 ("23:40", "00:25", 0.75, 0))
                self.assertEqual(record.entry_type, definition)
                self.assertEqual(record.context, WorkContext())
                self.assertIsNone(record.work_mode)
                self.assertIsNone(restored.timer)
                self.assertEqual(restored.default_work_mode(), WorkMode.REMOTE)

    def test_recording_sessions_apply_state_explicitly_and_reject_stale_timer_updates(self):
        initial = self.service.snapshot_state()
        session = self.service.new_session(initial)
        started = session.start("normal", "Recording")
        self.assertTrue(started.ok, started.error)
        self.assertEqual(self.service.snapshot_state(), initial)
        self.service.apply_state(session.snapshot_state())
        self.assertEqual(self.service.timer, started.value)
        stale = self.service.new_session(self.service.snapshot_state())
        current = self.service.new_session(self.service.snapshot_state())
        self.assertTrue(current.save_content("Updated recording").ok)
        rejected = stale.finish("Stale recording", now=self.now + timedelta(hours=1))
        self.assertEqual(rejected.error.code, "time_entry_timer_conflict")
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        finished = current.finish("Updated recording", now=self.now + timedelta(hours=1))
        self.assertTrue(finished.ok, finished.error)
        self.service.apply_state(current.snapshot_state())
        self.assertIsNone(self.service.timer)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), (finished.value,))

    def test_timer_discard_retries_failed_reads_without_removing_a_new_valid_timer(self):
        self.settings.set(self.user.id, "time_entry_timer", "invalid")
        with patch.object(self.settings, "get", side_effect=OSError("unavailable")):
            service = self.make_service()
        self.assertTrue(service.restore_failed)
        self.assertTrue(service.discard_timer().ok)
        self.assertIsNone(self.settings.get(self.user.id, "time_entry_timer"))
        with patch.object(self.settings, "get", side_effect=OSError("unavailable")):
            service = self.make_service()
        self.assertTrue(self.service.start("normal", "Current recording").ok)
        raw = self.settings.get(self.user.id, "time_entry_timer")
        self.assertEqual(service.discard_timer().error.code, "time_entry_timer_conflict")
        self.assertEqual(self.settings.get(self.user.id, "time_entry_timer"), raw)

    def test_timer_start_rechecks_occupied_time_within_its_write_transaction(self):
        start = self.now
        self.repository.save_entry(WorkLog(self.user.id, start.date(), start.strftime("%H:%M"),
                                          (start + timedelta(hours=1)).strftime("%H:%M"),
                                          started_at=start, ended_at=start + timedelta(hours=1)))
        raw = encode_timer(EntryTimer("new-capture", start + timedelta(minutes=15), EntryType.NORMAL))
        with self.assertRaisesRegex(ValueError, "worklog_entry_overlap"):
            self.repository.change_timer(self.user.id, None, raw)
        self.assertIsNone(self.settings.get(self.user.id, "time_entry_timer"))

    def test_captured_records_across_two_calendar_dates_still_conflict(self):
        start = datetime(2030, 1, 1, 23, tzinfo=timezone(timedelta(hours=-12)))
        old = WorkLog(self.user.id, start.date(), "23:00", "23:30", started_at=start, ended_at=start + timedelta(minutes=30))
        self.repository.save_entry(old)
        current = datetime(2030, 1, 3, 1, 15, tzinfo=timezone(timedelta(hours=14)))
        overlap = WorkLog(self.user.id, current.date(), "01:15", "01:25",
                          started_at=current, ended_at=current + timedelta(minutes=10))
        with self.assertRaisesRegex(ValueError, "worklog_entry_overlap"):
            self.repository.save_entry(overlap)
        self.assertEqual(len(self.repository.list_export_rows(self.user.id)), 1)

    def test_csv_preview_and_commit_allow_distinct_captured_dst_occurrences(self):
        from zoneinfo import ZoneInfo

        zone = ZoneInfo("America/New_York")
        entries = tuple(WorkLog(self.user.id, datetime(2026, 11, 1).date(), "01:10", "01:20",
                               started_at=datetime(2026, 11, 1, 1, 10, tzinfo=zone, fold=fold),
                               ended_at=datetime(2026, 11, 1, 1, 20, tzinfo=zone, fold=fold)) for fold in (0, 1))
        path = Path(self.directory.name) / "folds.csv"
        self.assertTrue(WorkLogCsvExporter().export_work_logs(path, entries).ok)
        result = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.repository).handle(
            ImportWorkLogsCsvCommand(self.user.id, path))
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.value.imported_count, 2)
        self.assertFalse(result.value.errors)
    def test_invalid_timer_blocks_writes_with_a_specific_error_and_can_be_discarded(self):
        for raw in ("invalid", "[]", "{}", '{"capture_id":"sample","started_at":"2030-01-01T09:00:00"}'):
            with self.subTest(raw=raw):
                self.settings.set(self.user.id, "time_entry_timer", raw)
                result = self.service.save_manual(self.now.date(), "09:00", "10:00", "normal", "New record")
                self.assertFalse(result.ok)
                self.assertEqual(result.error.code, "auto_record_restore_failed")
                self.assertEqual(self.settings.get(self.user.id, "time_entry_timer"), raw)
                recovered = TimeEntryService(user_id=self.user.id, repository=self.repository,
                                             settings=self.settings, local_timezone=timezone.utc)
                self.assertTrue(recovered.discard_timer().ok)
                self.assertIsNone(self.settings.get(self.user.id, "time_entry_timer"))

    def test_split_merge_and_undo_preserve_time_identity_and_revisions(self):
        saved = self.service.save_manual(self.now.date(), "09:00", "12:00", "meeting", "Review", work_mode=WorkMode.REMOTE).value
        split = self.service.split(saved, 60)
        self.assertTrue(split.ok, split.error)
        left, right = split.value
        self.assertEqual(left.id, saved.id)
        self.assertEqual((left.worked_hours(), right.worked_hours()), (1, 2))
        self.assertEqual((left.work_mode, right.work_mode), (WorkMode.REMOTE, WorkMode.REMOTE))
        self.assertFalse(self.service.split(saved, 30).ok)
        self.assertFalse(self.service.merge(right, left).ok)
        merged = self.service.merge(left, right)
        self.assertTrue(merged.ok, merged.error)
        self.assertEqual((merged.value.id, merged.value.worked_hours()), (saved.id, 3))
        self.assertEqual(merged.value.note, saved.note)
        self.assertEqual(merged.value.work_mode, WorkMode.REMOTE)
        self.assertEqual(self.service.latest_change().value.operation, "merge")
        restored = self.service.undo(self.service.latest_change().value.id)
        self.assertTrue(restored.ok, restored.error)
        self.assertEqual({record.id for record in restored.value}, {left.id, right.id})
        self.assertEqual(sum(record.worked_hours() for record in restored.value), 3)
        self.assertTrue(self.service.undo(self.service.latest_change().value.id).ok)
        original = self.repository.get_entry(self.user.id, saved.id)
        self.assertEqual((original.start_time, original.end_time, original.worked_hours()), ("09:00", "12:00", 3))
        self.assertEqual(original.work_mode, WorkMode.REMOTE)
        self.assertGreater(original.revision, merged.value.revision)
        self.assertTrue(self.service.undo(self.service.latest_change().value.id).ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, saved.day), ())
        self.assertIsNone(self.service.latest_change().value)

    def test_failed_transformations_preserve_records_and_reversible_history(self):
        saved = self.service.save_manual(self.now.date(), "09:00", "12:00", "normal", "Original").value
        insert = EntryWriteSession.insert

        def interrupted(session, record, **options):
            insert(session, record, **options)
            raise OSError("storage unavailable")

        def assert_preserved(operation):
            before = self.repository.list_for_day(self.user.id, saved.day)
            history = self.service.latest_change().value
            with patch.object(EntryWriteSession, "insert", autospec=True, side_effect=interrupted):
                result = operation()
            self.assertFalse(result.ok)
            self.assertEqual(self.repository.list_for_day(self.user.id, saved.day), before)
            self.assertEqual(self.service.latest_change().value, history)

        assert_preserved(lambda: self.service.split(saved, 60))
        self.assertTrue(self.service.split(saved, 60).ok)
        change_id = self.service.latest_change().value.id
        assert_preserved(lambda: self.service.undo(change_id))

    def test_reversible_record_changes_reject_conflicts_and_preserve_active_timing(self):
        saved = self.service.save_manual(self.now.date(), "07:00", "08:00", "normal", "Original").value
        updated = self.service.save_manual(saved.day, "07:00", "08:00", "normal", "Changed", saved).value
        change = self.service.latest_change().value
        self.assertTrue(self.service.start("normal", "Active").ok)
        self.assertFalse(self.service.undo(change.id).ok)
        self.assertEqual(self.repository.get_entry(self.user.id, saved.id), updated)
        self.assertTrue(self.service.discard_timer().ok)
        self.assertTrue(self.service.undo(change.id).ok)
        restored = self.repository.get_entry(self.user.id, saved.id)
        self.assertEqual(restored.note, "Original")
        self.assertFalse(self.service.save_content("Stale", saved).ok)
        self.assertTrue(self.service.delete(restored).ok)
        deletion = self.service.latest_change().value
        self.assertTrue(self.service.undo(deletion.id).ok)
        self.assertEqual(self.repository.get_entry(self.user.id, saved.id).note, "Original")
        with self.assertRaises(ValueError):
            self.repository.undo_change(self.user.id + 1, deletion.id)
        with self.factory.transaction() as connection:
            connection.execute("UPDATE entry_changes SET created_at=datetime('now','-31 days') WHERE user_id=?", (self.user.id,))
        self.assertIsNone(self.service.latest_change().value)
        self.assertFalse(self.service.undo(deletion.id).ok)

    def test_interval_operations_preserve_offsets_and_do_not_guess_historical_breaks(self):
        day = self.now.date()
        historical = self.repository.save_entry(WorkLog(self.user.id, day, "09:00", "18:00", 1, "Historical"))
        failed = self.service.split(historical, 240)
        self.assertEqual(failed.error.code, "historical_break_placement_required")
        self.assertEqual(self.repository.get_entry(self.user.id, historical.id), historical)
        converted = self.service.convert_break(historical, 180)
        self.assertTrue(converted.ok, converted.error)
        self.assertEqual([entry.entry_type.value for entry in converted.value], ["normal", "break", "normal"])
        self.assertEqual(sum(entry.worked_hours() for entry in converted.value), historical.worked_hours())
        self.assertTrue(self.service.undo(self.service.latest_change().value.id).ok)
        self.assertEqual(self.repository.get_entry(self.user.id, historical.id).break_hours, 1)
        start = self.now.replace(hour=22)
        end = start + timedelta(hours=4)
        overnight = self.repository.save_entry(WorkLog(self.user.id, day, "22:00", "02:00", note="Night",
            started_at=start, ended_at=end))
        split = self.service.split(overnight, 120)
        self.assertTrue(split.ok, split.error)
        self.assertEqual(sum(record.worked_hours() for record in split.value), 4)
        self.assertEqual(split.value[1].day, day + timedelta(days=1))
        self.assertEqual(split.value[0].ended_at, split.value[1].started_at)

    def test_manual_edits_preserve_captured_offsets_until_the_interval_changes(self):
        start = self.now.replace(hour=22, tzinfo=timezone(timedelta(hours=9)))
        end = start + timedelta(hours=8)
        original = self.repository.save_entry(WorkLog(self.user.id, start.date(), "22:00", "06:00",
            note="Night work", started_at=start, ended_at=end, capture_id="captured-interval"))
        result = self.service.save_manual(original.day, "22:00", "06:00", "normal", "Updated", original)
        self.assertTrue(result.ok, result.error)
        edited = result.value
        self.assertEqual((edited.started_at.isoformat(), edited.ended_at.isoformat()),
                         (start.isoformat(), end.isoformat()))
        self.assertEqual((edited.id, edited.capture_id, edited.worked_hours()),
                         (original.id, original.capture_id, 8))
        changed = self.service.save_manual(edited.day, "22:00", "07:00", "normal", "Extended", edited)
        self.assertTrue(changed.ok, changed.error)
        self.assertEqual(changed.value.started_at.utcoffset(), timedelta(0))
        self.assertEqual(changed.value.ended_at.date(), original.day + timedelta(days=1))
        self.assertEqual(changed.value.worked_hours(), 9)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "worklog.db"
        self.factory = SQLiteConnectionFactory(self.path)
        MigrationRunner(self.factory).run_pending()
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.user = auth.create_user("sample", "example-password", recovery_key=None, is_admin=False)
        self.repository = SQLiteWorkLogRepository(self.factory)
        self.settings = SQLiteSettingsRepository(self.factory)
        self.now = datetime(2026, 5, 20, 9, tzinfo=timezone.utc)
        self.service = self.make_service()

    def make_service(self):
        return TimeEntryService(user_id=self.user.id, repository=self.repository, settings=self.settings,
                                local_timezone=timezone.utc, clock=lambda: self.now,
                                entry_types=EntryTypeService(self.user.id, SQLiteEntryTypeRepository(self.factory)),
                                work_modes=WorkModeService(self.user.id, SQLiteWorkModeRepository(self.factory)))

    def test_custom_work_arrangements_preserve_record_and_timer_snapshots_across_catalog_changes(self):
        modes = self.service.work_modes
        original = modes.save("Hybrid", "work").value
        saved = self.service.save_manual(self.now.date(), "07:00", "08:00", "meeting", "Planning", work_mode=original).value
        self.assertEqual(self.service.default_work_mode().label, "Hybrid")
        self.assertTrue(self.service.start("normal", "Ongoing", work_mode=original).ok)
        renamed = modes.save("Flexible", "work", original).value
        self.assertEqual(modes.save("Stale", "work", original).error.code, "work_mode_conflict")
        self.assertEqual(modes.save("FLEXIBLE", "work").error.code, "work_mode_name_exists")
        self.assertEqual(self.make_service().timer.work_mode.label, "Hybrid")
        self.assertTrue(modes.archive(renamed).ok)
        self.assertIsNone(self.service.default_work_mode())
        restored = self.make_service()
        self.now += timedelta(hours=1)
        completed = restored.finish("Completed").value
        self.assertEqual(completed.work_mode.label, "Hybrid")
        self.assertEqual(self.repository.get_entry(self.user.id, saved.id).work_mode.label, "Hybrid")
        edited = restored.save_manual(saved.day, "07:00", "08:00", "meeting", "Edited", saved, work_mode=original)
        self.assertTrue(edited.ok, edited.error)
        self.assertEqual(edited.value.work_mode.label, "Hybrid")
        self.assertEqual(restored.start("normal", "Unavailable", work_mode=renamed).error.code, "work_mode_unavailable")
        self.assertEqual(restored.save_manual(saved.day, "11:00", "12:00", "normal", "Unavailable", work_mode=renamed).error.code, "work_mode_unavailable")
        recreated = modes.save("Flexible", "work").value
        self.assertNotEqual(recreated.value, original.value)

    def test_custom_work_arrangements_survive_split_undo_csv_and_analytics_without_catalog_leakage(self):
        from worklogger.domain.worklog.search import EntryFilter
        from worklogger.infrastructure.entry_type_labels import classification_label
        mode = self.service.work_modes.save("=Hybrid team", "work").value
        saved = self.service.save_manual(self.now.date(), "09:00", "12:00", "normal", "Team work", work_mode=mode).value
        split = self.service.split_at(saved, self.now + timedelta(hours=1))
        self.assertTrue(split.ok, split.error)
        self.assertEqual([entry.work_mode.label for entry in split.value], [mode.label, mode.label])
        undone = self.service.undo(self.service.latest_change().value.id)
        self.assertTrue(undone.ok, undone.error)
        self.assertEqual(undone.value[0].work_mode.label, mode.label)
        path = Path(self.directory.name) / "arrangements.csv"
        self.assertTrue(WorkLogCsvExporter().export_work_logs(path, undone.value).ok)
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        other = auth.create_user("other-mode-owner", "example-password", recovery_key=None, is_admin=False)
        importer = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.repository)
        preview = importer.preview(ImportWorkLogsCsvCommand(other.id, path)).value
        self.assertFalse(preview.errors)
        self.assertTrue(importer.apply(preview).ok)
        copied = self.repository.search_entries(other.id, EntryFilter(saved.day, saved.day)).entries[0]
        self.assertEqual(copied.work_mode.label, mode.label)
        self.assertIn(mode.label, classification_label(copied.entry_type, copied.work_mode))
        self.assertEqual(SQLiteWorkModeRepository(self.factory).list_types(other.id), ())
        data = dashboard_data((copied,), year=2026, month=5, scope="monthly", standard_hours=8, monthly_target=160)
        self.assertEqual(dict(data.work_modes), {mode: 3})

    def test_custom_classifications_keep_accounting_snapshots_across_catalog_changes(self):
        types = self.service.entry_types
        work = types.save("Research", "work").value
        saved = self.service.save_manual(self.now.date(), "09:00", "11:00", work.value, "Reading").value
        changed = types.save("Personal break", "break", work).value
        self.assertFalse(types.save("Another name", "work", work).ok)
        self.assertFalse(types.save("personal BREAK", "work").ok)
        rest = self.service.save_manual(self.now.date(), "11:00", "12:00", changed.value, "Rest").value
        self.assertEqual((saved.worked_hours(), rest.worked_hours()), (2, 0))
        self.assertTrue(types.archive(changed).ok)
        self.assertFalse(self.service.save_manual(self.now.date(), "12:00", "13:00", changed.value, "Unavailable").ok)
        edited = self.service.save_manual(saved.day, "09:00", "10:00", work.value, "Updated", saved).value
        loaded = self.repository.get_entry(self.user.id, edited.id)
        self.assertEqual((loaded.entry_type.label, loaded.entry_type.category, loaded.worked_hours()), ("Research", "work", 1))
        summary = self.repository.list_all(self.user.id)
        data = dashboard_data(summary, year=2026, month=5, scope="monthly", standard_hours=8, monthly_target=160)
        self.assertEqual((data.stats.total_hours, data.stats.rest_days), (1, 1))
        self.assertEqual({definition.label: hours for definition, hours in data.entry_types}, {"Research": 1, "Personal break": 1})
        other = EntryTypeService(self.user.id + 1, SQLiteEntryTypeRepository(self.factory))
        self.assertEqual(other.list_types().value, ())
        self.assertFalse(other.archive(changed).ok)
        with self.assertRaises(ValueError):
            other.resolve(work.value)

    def test_custom_types_survive_timer_restore_and_csv_round_trip(self):
        definition = self.service.entry_types.save("Research", "work").value
        self.assertTrue(self.service.start(definition.value, "Draft", work_mode=WorkMode.REMOTE).ok)
        self.assertTrue(self.service.entry_types.save("Lunch", "break", definition).ok)
        restored = self.make_service()
        self.assertEqual((restored.timer.entry_type.label, restored.timer.entry_type.category), ("Research", "work"))
        self.assertEqual(restored.timer.work_mode, WorkMode.REMOTE)
        self.now += timedelta(hours=1)
        saved = restored.finish("Completed").value
        csv_path = Path(self.directory.name) / "custom.csv"
        self.assertTrue(WorkLogCsvExporter().export_work_logs(csv_path, (saved,)).ok)
        importer = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.repository)
        preview = importer.preview(ImportWorkLogsCsvCommand(self.user.id, str(csv_path))).value
        self.assertEqual(preview.errors, ())
        self.assertEqual(preview.rows[0].entry_type.label, "Research")
        self.assertEqual(preview.rows[0].worked_hours(), 1)
        self.assertEqual(preview.rows[0].work_mode, WorkMode.REMOTE)
        self.settings.set(self.user.id, "last_used_work_mode", WorkMode.ONSITE.value)
        self.assertTrue(importer.apply(preview, overwrite=True).ok)
        imported = self.repository.list_for_day(self.user.id, saved.day)[0]
        self.assertEqual(imported.entry_type.category, "work")
        self.assertEqual(imported.work_mode, WorkMode.REMOTE)
        self.assertEqual(restored.default_work_mode(), WorkMode.ONSITE)

    def test_multiple_entries_edit_delete_and_daily_statistics(self):
        first = self.service.save_manual(self.now.date(), "09:00", "12:00", "meeting", "Planning").value
        rest = self.service.save_manual(self.now.date(), "12:00", "13:00", "break", "Lunch").value
        last = self.service.save_manual(self.now.date(), "13:00", "18:00", "training", "Practice").value
        self.assertEqual(len({first.id, rest.id, last.id}), 3)
        summary = self.repository.get_for_day(self.user.id, self.now.date())
        self.assertEqual(summary.worked_hours(), 8)
        data = dashboard_data(self.repository.list_all(self.user.id), year=2026, month=5, scope="monthly", standard_hours=7, monthly_target=160)
        self.assertEqual((data.stats.total_hours, data.stats.work_days, data.stats.overtime_hours), (8, 1, 1))
        self.assertEqual(dict(data.entry_types), {"meeting": 3, "break": 1, "training": 5})
        self.assertEqual(dict(data.work_modes), {None: 8})
        updated = self.service.save_manual(first.day, "09:00", "11:00", "meeting", "Updated", first).value
        self.assertEqual(updated.id, first.id)
        self.assertEqual(updated.revision, 1)
        self.assertFalse(self.service.save_manual(first.day, "09:00", "10:00", "normal", "Stale", first).ok)
        self.assertTrue(self.service.delete(rest).ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, first.day)), 2)
        with self.assertRaises(ValueError):
            self.repository.delete_entry(self.user.id + 1, last.id, last.revision)

    def test_overlaps_are_rejected_including_overnight_and_active_timers(self):
        day = self.now.date()
        self.assertTrue(self.service.save_manual(day, "22:00", "06:00", "normal", "Night work").ok)
        self.assertFalse(self.service.save_manual(day + timedelta(days=1), "05:00", "07:00", "meeting", "Overlap").ok)
        self.assertTrue(self.service.save_manual(day + timedelta(days=1), "06:00", "07:00", "meeting", "Adjacent").ok)
        self.assertTrue(self.service.start("normal", "Active").ok)
        self.assertFalse(self.service.save_manual(day, "10:00", "11:00", "normal", "Reserved").ok)
        self.assertTrue(self.service.save_manual(day, "07:00", "09:00", "normal", "Before timer").ok)

    def test_automatic_recording_restores_content_and_saves_time_on_finish(self):
        clicked_start = self.now
        self.now += timedelta(minutes=1)
        self.assertTrue(self.service.start("meeting", "Initial", now=clicked_start).ok)
        self.assertTrue(self.service.save_content("Updated").ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        resumed = self.make_service()
        self.assertEqual(resumed.timer.content, "Updated")
        clicked_end = clicked_start + timedelta(hours=2)
        self.now = clicked_end + timedelta(minutes=1)
        saved = resumed.finish("Final", now=clicked_end).value
        self.assertEqual((saved.note, saved.worked_hours()), ("Final", 2))
        self.assertIsNone(self.make_service().timer)
        updated = resumed.save_content("Edited after stopping", saved).value
        self.assertEqual(updated.id, saved.id)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 1)
        deadline = clicked_end + timedelta(hours=1)
        scheduled = EntryTimer("saved-break", clicked_end, EntryType.BREAK, break_until=deadline,
                               resume_type=EntryType.REMOTE, resume_content="Continued work")
        self.repository.change_timer(self.user.id, None, encode_timer(scheduled))
        restored = self.make_service()
        self.now = deadline + timedelta(minutes=15)
        self.assertTrue(restored.advance().ok)
        self.assertEqual(restored.timer.started_at, deadline)
        self.assertEqual(restored.timer.entry_type, EntryType.REMOTE)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 2)

    def test_resuming_a_saved_break_preserves_custom_work_arrangement(self):
        mode = self.service.work_modes.save("Hybrid", "work").value
        deadline = self.now + timedelta(hours=1)
        timer = EntryTimer("saved-break-mode", self.now, EntryType.BREAK, break_until=deadline,
                           resume_type=EntryType.NORMAL, work_mode=mode)
        self.repository.change_timer(self.user.id, None, encode_timer(timer))
        restored = self.make_service()
        self.now = deadline
        self.assertTrue(restored.advance().ok)
        self.assertEqual(restored.timer.work_mode, mode)
        self.assertEqual(self.make_service().timer.work_mode, mode)
        self.now += timedelta(hours=1)
        self.assertEqual(restored.finish("Continued work").value.work_mode, mode)

    def test_fixed_break_is_saved_immediately_with_captured_times_and_no_timer(self):
        clicked = self.now.replace(hour=23, minute=30, second=17)
        self.now = clicked + timedelta(minutes=1)
        result = self.service.take_break(1.75, "Rest", now=clicked)
        self.assertTrue(result.ok, result.error)
        stored = self.repository.list_for_day(self.user.id, clicked.date())[0]
        self.assertEqual((stored.entry_type, stored.note, stored.start_time, stored.end_time), (EntryType.BREAK, "Rest", "23:30", "01:15"))
        self.assertEqual(stored.started_at, clicked)
        self.assertEqual(stored.ended_at, clicked + timedelta(hours=1.75))
        self.assertEqual(stored.worked_hours(), 0)
        restored = self.make_service()
        self.assertIsNone(restored.timer)
        self.assertFalse(restored.start("normal", "Overlapping work").ok)
        self.now = stored.ended_at
        self.assertTrue(restored.advance().ok)
        self.assertIsNone(restored.timer)
        self.assertTrue(restored.start("normal", "Next work").ok)

    def test_break_validation_and_failed_writes_preserve_records_and_timer_state(self):
        for hours in (0, -1, 4.1, float("nan"), float("inf")):
            self.assertFalse(self.service.take_break(hours, "Invalid").ok)
        stale = self.make_service()
        self.assertTrue(self.service.start("meeting", "Active").ok)
        self.assertEqual(self.service.take_break(1, "Rest").error.code, "auto_record_already_active")
        self.assertFalse(stale.take_break(1, "Stale request").ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        self.assertEqual(self.make_service().timer.entry_type, EntryType.MEETING)
        self.now += timedelta(hours=1)
        self.assertTrue(self.service.finish("Completed").ok)
        with patch.object(EntryWriteSession, "change_timer", side_effect=OSError("storage unavailable")):
            self.assertFalse(self.service.take_break(1, "Rest").ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 1)
        self.assertIsNone(self.make_service().timer)
        self.assertTrue(self.service.take_break(1, "Rest").ok)
        self.assertFalse(self.service.take_break(1, "Overlapping rest").ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 2)
        saved_break = self.repository.list_for_day(self.user.id, self.now.date())[-1]
        updated = self.service.save_manual(saved_break.day, saved_break.start_time, saved_break.end_time,
                                           "break", "Changed elsewhere", saved_break).value
        early = self.now + timedelta(minutes=1)
        self.assertEqual(self.service.start("normal", "Work", now=early, break_entry=saved_break).error.code, "worklog_entry_conflict")
        self.assertIsNone(self.service.timer)
        self.assertEqual(self.repository.get_entry(self.user.id, updated.id), updated)
        tomorrow = self.now.date() + timedelta(days=1)
        self.assertTrue(self.service.save_manual(tomorrow, "09:00", "10:00", "break", "Manual rest").ok)
        manual_start = self.now.replace(hour=9, minute=30) + timedelta(days=1)
        self.assertEqual(self.service.start("normal", "Work", now=manual_start).error.code, "worklog_entry_overlap")

    def test_confirmed_early_start_changes_break_and_timer_together(self):
        for elapsed in (timedelta(minutes=1), timedelta(0)):
            self.now += timedelta(days=1)
            record = self.service.take_break(1, "Lunch").value
            clicked = self.now + elapsed
            offered = self.service.start("meeting", "Work", now=clicked)
            self.assertEqual(offered.error.code, "fixed_break_active")
            self.assertEqual(offered.error.details["break_entry"], record)
            with patch.object(EntryWriteSession, "change_timer", side_effect=OSError("storage unavailable")):
                self.assertFalse(self.service.start("meeting", "Work", now=clicked, break_entry=record).ok)
            self.assertEqual(self.repository.get_entry(self.user.id, record.id), record)
            self.assertIsNone(self.make_service().timer)
            started = self.service.start("meeting", "Work", now=clicked, break_entry=record)
            self.assertTrue(started.ok, started.error)
            self.assertEqual(self.make_service().timer.started_at, clicked)
            changed = self.repository.get_entry(self.user.id, record.id)
            if elapsed:
                self.assertEqual((changed.started_at, changed.ended_at, changed.note), (record.started_at, clicked, "Lunch"))
                self.assertEqual(changed.revision, record.revision + 1)
            else:
                self.assertIsNone(changed)
            self.assertTrue(self.service.finish("Work", now=clicked + timedelta(minutes=30)).ok)
            entries = self.repository.list_for_day(self.user.id, record.day)
            self.assertEqual(sum(entry.worked_hours() for entry in entries), 0.5)

    def test_failed_automatic_transition_rolls_back_record_and_preserves_timer(self):
        self.service.start("normal", "Retained")
        self.now += timedelta(hours=1)
        with patch.object(EntryWriteSession, "change_timer", side_effect=OSError("storage unavailable")):
            self.assertFalse(self.service.finish("Changed").ok)
        self.assertEqual(self.repository.list_for_day(self.user.id, self.now.date()), ())
        self.assertEqual(self.make_service().timer.content, "Retained")
        self.assertTrue(self.service.finish("Changed").ok)
        self.assertFalse(self.service.finish("Changed").ok)
        self.assertEqual(len(self.repository.list_for_day(self.user.id, self.now.date())), 1)

    def test_current_record_restart_preserves_content_breaks_and_offsets(self):
        path = Path(self.directory.name) / "previous.db"
        factory = SQLiteConnectionFactory(path)
        MigrationRunner(factory).run_pending()
        auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        user = auth.create_user("previous", "example-password", recovery_key=None, is_admin=False)
        repository = SQLiteWorkLogRepository(factory)
        record = WorkLog(user.id, self.now.date(), "09:00", "18:00", 1, "History", EntryType.REMOTE,
                         started_at=self.now, ended_at=self.now + timedelta(hours=9), work_mode=WorkMode.REMOTE)
        repository.save_entry(record)
        self.assertEqual(MigrationRunner(factory).run_pending(), ())
        current = SQLiteWorkLogRepository(factory).list_for_day(user.id, record.day)[0]
        self.assertEqual((current.note, current.break_hours, current.worked_hours(), current.started_at), ("History", 1, 8, record.started_at))
        self.assertEqual(current.work_mode, WorkMode.REMOTE)
        self.assertFalse(list(path.parent.glob("previous.db.bak_upgrade_*")))
        self.assertEqual(MigrationRunner(factory).run_pending(), ())

    def test_portability_preserves_periods_types_notes_and_distinct_calendar_identifiers(self):
        day = self.now.date()
        for start, end, kind, content in (("09:00", "12:00", "meeting", "Planning"),
                                         ("12:00", "13:00", "break", "Lunch"),
                                         ("13:00", "17:00", "other", "Practice")):
            self.assertTrue(self.service.save_manual(day, start, end, kind, content).ok)
        SQLiteDailyNoteRepository(self.factory).save(DailyNote(self.user.id, day, "Independent daily note"))
        path = Path(self.directory.name) / "records.csv"
        records = self.repository.list_export_rows(self.user.id)
        self.assertTrue(WorkLogCsvExporter().export_work_logs(path, records).ok)
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        other = auth.create_user("other", "example-password", recovery_key=None, is_admin=False)
        importer = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.repository)
        preview = importer.preview(ImportWorkLogsCsvCommand(other.id, path)).value
        self.assertFalse(preview.errors)
        self.assertEqual(len(preview.rows), 4)
        self.assertTrue(importer.apply(preview).ok)
        self.assertEqual(self.repository.get_for_day(other.id, day).worked_hours(), 7)
        self.assertEqual(self.repository.list_for_day(other.id, day)[-1].entry_type, EntryType.OTHER)
        self.assertEqual(SQLiteDailyNoteRepository(self.factory).get_for_day(other.id, day).content, "Independent daily note")
        exported = WorkLogIcsExporter().export_work_logs(self.repository.list_all(self.user.id)).value
        identifiers = [line for line in exported.splitlines() if line.startswith("UID:")]
        self.assertEqual(len(identifiers), 3)
        self.assertEqual(len(set(identifiers)), 3)

    def test_single_record_import_preserves_independent_memo_semantics(self):
        day = self.now.date()
        self.assertTrue(self.service.save_manual(day, "09:00", "10:00", "normal", "Record content").ok)
        path = Path(self.directory.name) / "single-record.csv"
        self.assertTrue(WorkLogCsvExporter().export_work_logs(path, self.repository.list_export_rows(self.user.id)).ok)
        auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        other = auth.create_user("single-import", "example-password", recovery_key=None, is_admin=False)
        importer = ImportWorkLogsCsvHandler(importer=WorkLogCsvImporter(), repository=self.repository)
        preview = importer.preview(ImportWorkLogsCsvCommand(other.id, path)).value
        self.assertTrue(importer.apply(preview).ok)
        notes = SQLiteDailyNoteRepository(self.factory)
        self.assertEqual(notes.get_for_day(other.id, day).content, "")
        notes.save(DailyNote(other.id, day, "Independent memo"))
        self.assertTrue(importer.apply(preview, overwrite=True).ok)
        self.assertEqual(notes.get_for_day(other.id, day).content, "Independent memo")
        self.assertEqual(self.repository.list_for_day(other.id, day)[0].note, "Record content")

    def test_invalid_optional_offsets_do_not_hide_valid_clock_records(self):
        record = self.service.save_manual(self.now.date(), "09:00", "10:00", "normal", "Retained content").value
        with self.factory.transaction() as connection:
            connection.execute("UPDATE worklog SET started_at='invalid',ended_at=NULL WHERE id=?", (record.id,))
        with self.assertLogs("worklogger.infrastructure.repositories._mapping", level="WARNING"):
            loaded = self.repository.list_for_day(self.user.id, self.now.date())[0]
        self.assertEqual((loaded.id, loaded.note, loaded.worked_hours()), (record.id, "Retained content", 1))
        self.assertIsNone(loaded.started_at)
        self.assertIsNone(loaded.ended_at)
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT started_at FROM worklog WHERE id=?", (record.id,)).fetchone()[0], "invalid")

    def test_stored_nonwork_metadata_is_rejected_without_changing_the_record(self):
        record = self.service.save_manual(self.now.date(), "09:00", "10:00", "normal", "Retained content").value
        for entry_type, work_mode, project_label in (
            ("break", "remote", ""), ("break", None, "Platform"), ("sick_leave", None, "Platform"),
        ):
            with self.subTest(entry_type=entry_type, work_mode=work_mode, project_label=project_label):
                with self.factory.transaction(write=True) as connection:
                    connection.execute("UPDATE worklog SET entry_type=?,work_mode=?,project_label=? WHERE id=?",
                                       (entry_type, work_mode, project_label, record.id))
                with self.assertRaisesRegex(ValueError, "stored_work_logs_invalid"):
                    self.repository.list_for_day(self.user.id, record.day)
                with self.factory.connection() as connection:
                    stored = connection.execute("SELECT entry_type,work_mode,project_label,note FROM worklog WHERE id=?",
                                                (record.id,)).fetchone()
                self.assertEqual(tuple(stored), (entry_type, work_mode, project_label, "Retained content"))
