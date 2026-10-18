"""Personal backup isolation, archive authentication, and atomic restoration."""

from dataclasses import replace
from datetime import date
import json
import unittest

from tests.infrastructure import test_data_portability_infrastructure as portability
from worklogger.infrastructure.backup.archive import PersonalBackupArchive
from worklogger.infrastructure.backup.personal_data import SQLitePersonalData, document_digest
from worklogger.infrastructure.repositories import SQLiteWorkLogRepository
from worklogger.domain.worklog.models import WorkLog


class PersonalBackupTests(unittest.TestCase):
    def setUp(self):
        fixture = portability.DataPortabilityInfrastructureTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.factory = fixture.factory
        self.owner = fixture.register_user("backup-owner")
        self.other = fixture.register_user("other-owner")
        self.repository = SQLiteWorkLogRepository(self.factory)
        for owner, note in ((self.owner, "Personal work"), (self.other, "Private other work")):
            self.repository.save_entry(WorkLog(owner, date(2026, 10, 18), "09:00", "12:00", note=note))
        with self.factory.transaction(write=True) as connection:
            connection.executemany("INSERT INTO settings(user_id,key,value) VALUES(?,?,?)", (
                (self.owner, "secret:ai_api_key", "never-upload"),
                (self.owner, "cloud_backup.configuration", "local-cloud-settings"),
                (self.owner, "standard_work_hours", "8")))
        self.personal = SQLitePersonalData(self.factory, self.owner)

    def test_snapshot_contains_only_portable_owned_data_and_restores_without_credentials(self):
        document = self.personal.capture()
        self.assertIn(b"Personal work", document)
        self.assertNotIn(b"Private other work", document)
        self.assertNotIn(b"never-upload", document)
        self.assertNotIn(b"password_hash", document)
        self.assertNotIn(b"local-cloud-settings", document)
        record = self.repository.list_for_day(self.owner, date(2026, 10, 18))[0]
        self.repository.save_entry(replace(record, note="Later work"))
        before = self.personal.capture()
        recovery = []
        self.personal.restore(document, expected_digest=document_digest(before), before_replace=recovery.append)
        self.assertEqual(recovery, [before])
        self.assertEqual(self.repository.list_for_day(self.owner, date(2026, 10, 18))[0].note, "Personal work")
        self.assertEqual(self.repository.list_for_day(self.other, date(2026, 10, 18))[0].note, "Private other work")
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT value FROM settings WHERE user_id=? AND key='secret:ai_api_key'", (self.owner,)).fetchone()[0], "never-upload")

    def test_restore_rejects_stale_confirmation_and_rolls_back_invalid_relationships(self):
        document = self.personal.capture()
        with self.assertRaisesRegex(ValueError, "cloud_local_changed"):
            self.personal.restore(document, expected_digest="stale", before_replace=lambda _data: None)
        value = json.loads(document)
        value["tables"]["worklog"][0]["project_id"] = "missing-project"
        with self.assertRaises(ValueError):
            self.personal.restore(json.dumps(value).encode(), expected_digest=document_digest(document), before_replace=lambda _data: None)
        self.assertEqual(self.personal.capture(), document)
        with self.factory.transaction(write=True) as connection:
            connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,'time_entry_timer','running')", (self.owner,))
        with self.assertRaisesRegex(ValueError, "cloud_timer_active"):
            self.personal.restore(document, expected_digest=document_digest(document), before_replace=lambda _data: None)

    def test_encrypted_archives_require_the_correct_passphrase_and_authenticate_contents(self):
        archive = PersonalBackupArchive()
        document = self.personal.capture()
        encrypted = archive.encode(document, encrypted=True, passphrase="example-backup-passphrase")
        self.assertNotIn(b"Personal work", encrypted)
        self.assertEqual(archive.decode(encrypted, passphrase="example-backup-passphrase"), document)
        for candidate, password in ((encrypted, "incorrect-passphrase"),
                                    (encrypted[:-1] + bytes([encrypted[-1] ^ 1]), "example-backup-passphrase")):
            with self.assertRaisesRegex(ValueError, "cloud_decryption_failed"):
                archive.decode(candidate, passphrase=password)
        plain = archive.encode(document, encrypted=False)
        self.assertEqual(archive.decode(plain), document)
