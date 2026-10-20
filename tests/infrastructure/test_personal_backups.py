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
    def test_cloud_and_local_recovery_round_trip_current_account_without_replacing_other_accounts(self):
        from pathlib import Path
        from tests.app.test_cloud_backups import MemoryObjects
        from tests.infrastructure.test_proxy_credentials import FakeKeyring
        from worklogger.app.use_cases.cloud_backups import CloudBackupService
        from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials
        from worklogger.infrastructure.backup.configuration import CloudBackupConfigurationStore
        from worklogger.infrastructure.backup.recovery import PersonalRecoveryStore
        from worklogger.infrastructure.repositories import SQLiteSettingsRepository
        from worklogger.infrastructure.security.key_store import SystemCredentialStore
        configuration = CloudBackupConfigurationStore(SQLiteSettingsRepository(self.factory),
            SystemCredentialStore(namespace="synthetic-personal-recovery", backend=FakeKeyring()), self.owner)
        remote = MemoryObjects()
        recovery = PersonalRecoveryStore(Path(self.factory.database_path).parent / "personal-recovery")
        service = CloudBackupService(configuration=configuration, personal_data=self.personal,
            archive=PersonalBackupArchive(), store_factory=lambda *_args: remote, recovery_store=recovery)
        password = "independent-backup-passphrase"
        self.assertTrue(service.configure(BackupConfiguration(endpoint="https://storage.example"),
            BackupCredentials("user", "secret", passphrase=password)).ok)
        self.assertTrue(service.upload().ok)
        record = self.repository.list_for_day(self.owner, date(2026, 10, 18))[0]
        self.repository.save_entry(replace(record, note="After upload"))
        overview = service.overview().value
        latest = overview.versions[0].revision
        result = service.download(latest, expected_revision=latest, expected_local_digest=overview.local_digest, force=True)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(self.repository.list_for_day(self.owner, record.day)[0].note, "Personal work")
        self.assertNotIn(b"After upload", recovery.read(result.value.recovery_path))
        preview = service.preview_local(result.value.recovery_path).value
        restored = service.restore_local(result.value.recovery_path, expected_local_digest=preview.local_digest,
            expected_archive_digest=preview.archive_digest, passphrase=password)
        self.assertTrue(restored.ok, restored.error)
        self.assertEqual(self.repository.list_for_day(self.owner, record.day)[0].note, "After upload")
        self.assertEqual(self.repository.list_for_day(self.other, record.day)[0].note, "Private other work")
        self.assertEqual(configuration.state()["last_error"], "cloud_local_changed")
        changed = Path(result.value.recovery_path)
        changed.write_bytes(changed.read_bytes() + b"changed")
        self.assertEqual(service.restore_local(changed, expected_local_digest=preview.local_digest,
            expected_archive_digest=preview.archive_digest, passphrase=password).error.code, "cloud_local_changed")

    def test_personal_restore_remaps_arrangement_catalogs_and_reads_predecessor_snapshots(self):
        from worklogger.app.use_cases.work_modes import WorkModeService
        from worklogger.infrastructure.repositories.entry_type_sqlite import SQLiteWorkModeRepository
        modes = WorkModeService(self.owner, SQLiteWorkModeRepository(self.factory))
        mode = modes.save("Hybrid", "work").value
        record = self.repository.list_for_day(self.owner, date(2026, 10, 18))[0]
        self.repository.save_entry(replace(record, work_mode=mode))
        document = self.personal.capture()
        self.personal.restore(document, expected_digest=document_digest(document), before_replace=lambda _data: None)
        restored = self.repository.list_for_day(self.owner, record.day)[0]
        self.assertEqual(restored.work_mode.label, "Hybrid")
        self.assertNotEqual(restored.work_mode.value, mode.value)
        self.assertEqual(restored.work_mode.value, modes.list_types().value[0].value)
        invalid = json.loads(self.personal.capture())
        invalid["tables"]["work_modes"][0]["name"] = ""
        before = self.personal.capture()
        with self.assertRaises(ValueError):
            self.personal.restore(json.dumps(invalid).encode(), expected_digest=document_digest(before), before_replace=lambda _data: None)
        self.assertEqual(self.personal.capture(), before)
        value = json.loads(self.personal.capture())
        value["schema"] = 17
        value["tables"].pop("work_modes")
        for row in value["tables"]["worklog"]:
            row["work_mode"] = "remote"
            row.pop("work_mode_label")
        before = self.personal.capture()
        self.personal.restore(json.dumps(value).encode(), expected_digest=document_digest(before), before_replace=lambda _data: None)
        self.assertEqual(self.repository.list_for_day(self.owner, record.day)[0].work_mode.value, "remote")

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
        for length in (14, 28, 44):
            with self.subTest(length=length), self.assertRaisesRegex(ValueError, "cloud_backup_invalid"):
                archive.decode(encrypted[:len(b"WL-PERSONAL-1\n") + length], passphrase="example-backup-passphrase")
        self.assertNotIn(b"Personal work", encrypted)
        self.assertEqual(archive.decode(encrypted, passphrase="example-backup-passphrase"), document)
        for candidate, password in ((encrypted, "incorrect-passphrase"),
                                    (encrypted[:-1] + bytes([encrypted[-1] ^ 1]), "example-backup-passphrase")):
            with self.assertRaisesRegex(ValueError, "cloud_decryption_failed"):
                archive.decode(candidate, passphrase=password)
        plain = archive.encode(document, encrypted=False)
        self.assertEqual(archive.decode(plain), document)
