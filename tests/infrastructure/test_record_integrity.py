"""Safe inspection and recovery of account-owned invalid record values."""

from contextlib import contextmanager
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tests.infrastructure import test_data_portability_infrastructure as portability
from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.app.use_cases.record_integrity import RecordIntegrityService
from worklogger.app.use_cases.work_logs import GetMonthRecordsHandler
from worklogger.domain.worklog.models import WorkLog
from worklogger.infrastructure.repositories import SQLiteWorkLogRepository
from worklogger.infrastructure.repositories.record_integrity_sqlite import SQLiteRecordIntegrity


class RecordIntegrityTests(unittest.TestCase):
    def setUp(self):
        fixture = portability.DataPortabilityInfrastructureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.factory = fixture.factory
        self.owner, self.other = fixture.register_user("owner"), fixture.register_user("other")
        fixture.save_work_log(self.owner, date(2026, 10, 5), note="Valid record")
        with self.factory.transaction(write=True) as connection:
            for owner in (self.owner, self.other):
                connection.execute('INSERT INTO worklog(user_id,d,start,end,"break",note) VALUES(?,?,?,?,?,?)',
                                   (owner, "2026-10-06", "09:00", "10:00", 99, "Private original value"))
        self.repository = SQLiteRecordIntegrity(self.factory)
        self.service = RecordIntegrityService(self.owner, self.repository)
        self.destination = Path(fixture._tempdir.name) / "recovery.json"

    def test_recovery_preserves_original_values_and_only_removes_reviewed_invalid_rows(self):
        result = GetMonthRecordsHandler(SQLiteWorkLogRepository(self.factory)).handle(
            GetMonthRecordsQuery(self.owner, 2026, 10))
        self.assertEqual(result.error.code, "stored_work_logs_invalid")
        inspection = self.service.inspect().value
        self.assertEqual(len(inspection.records), 1)
        self.assertEqual(inspection.records[0].stored_date, "2026-10-06")
        repository = SQLiteWorkLogRepository(self.factory)
        replacement = WorkLog(self.owner, date(2026, 10, 6), "09:00", "10:00")
        with self.assertRaisesRegex(ValueError, "stored_work_logs_invalid"):
            repository.save_entry(replacement)
        recovered = self.service.archive_invalid(inspection, self.destination)
        self.assertTrue(recovered.ok, recovered.error)
        self.assertEqual(recovered.value, 1)
        document = json.loads(self.destination.read_bytes())
        self.assertEqual(document["records"][0]["break"], 99)
        self.assertEqual(document["records"][0]["note"], "Private original value")
        self.assertEqual(document["records"][0]["id"], inspection.records[0].record_id)
        records = SQLiteWorkLogRepository(self.factory).list_for_month(self.owner, 2026, 10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].note, "Valid record")
        self.assertIsNotNone(repository.save_entry(replacement).id)
        self.assertEqual(len(self.repository.inspect(self.other).records), 1)

    def test_changed_confirmation_active_timer_and_existing_copy_do_not_remove_data(self):
        original = self.service.inspect().value
        with self.factory.transaction(write=True) as connection:
            connection.execute("UPDATE worklog SET note='Changed' WHERE id=?", (original.records[0].record_id,))
        self.assertEqual(self.service.archive_invalid(original, self.destination).error.code, "worklog_entry_conflict")
        self.assertFalse(self.destination.exists())
        current = self.service.inspect().value
        self.destination.write_text("Retained copy", encoding="utf-8")
        self.assertFalse(self.service.archive_invalid(current, self.destination).ok)
        self.assertEqual(self.destination.read_text(encoding="utf-8"), "Retained copy")
        with self.factory.transaction(write=True) as connection:
            connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,'time_entry_timer','active')", (self.owner,))
        self.assertEqual(self.service.archive_invalid(current, self.destination).error.code, "record_recovery_timer_active")
        self.assertEqual(self.service.inspect().value, current)

    def test_failed_commit_rolls_back_removal_and_retains_the_recovery_copy(self):
        original = self.service.inspect().value
        transaction = self.factory.transaction

        @contextmanager
        def fail_commit(*args, **kwargs):
            with transaction(*args, **kwargs) as connection:
                yield connection
                raise OSError("Synthetic commit failure")

        with patch.object(self.factory, "transaction", side_effect=fail_commit):
            self.assertFalse(self.service.archive_invalid(original, self.destination).ok)
        self.assertTrue(self.destination.is_file())
        self.assertEqual(self.service.inspect().value, original)
