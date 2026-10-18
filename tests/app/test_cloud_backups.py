"""Cloud version conflicts, authenticated transfers, and retention behavior."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import hashlib
import unittest

from worklogger.app.use_cases.cloud_backups import CloudBackupService
from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials, StoredObject, backup_due
from worklogger.infrastructure.backup.archive import PersonalBackupArchive


class MemoryConfiguration:
    def __init__(self):
        self.configuration = BackupConfiguration(endpoint="https://storage.example", encrypted=False, keep_count=2)
        self.value = {}
    def load(self):
        return self.configuration
    def secrets(self):
        return BackupCredentials("user", "password", passphrase="example-backup-passphrase")
    def state(self):
        return dict(self.value)
    def save_state(self, state):
        self.value = dict(state)


class MemoryObjects:
    def __init__(self):
        self.objects = {}
        self.race = None
    def test_connection(self):
        pass
    def get(self, key, *, limit):
        value = self.objects.get(key)
        return StoredObject(value, '"' + hashlib.sha256(value).hexdigest() + '"') if value is not None else None
    def put(self, key, data, *, expected_etag):
        if key == "head.json" and self.race:
            self.race()
        current = self.get(key, limit=1)
        if (current.etag if current else None) != expected_etag:
            raise ValueError("cloud_conflict")
        self.objects[key] = data
    def delete(self, key):
        self.objects.pop(key, None)


class MemoryPersonalData:
    def __init__(self):
        self.data = b"personal data"
    def capture(self):
        return self.data
    def restore(self, document, *, expected_digest, before_replace, sync_state=None):
        if hashlib.sha256(self.data).hexdigest() != expected_digest:
            raise ValueError("cloud_local_changed")
        before_replace(self.data)
        self.data = document
        digest = hashlib.sha256(document).hexdigest()
        self.configuration.save_state({**sync_state, "local_digest": digest})
        return digest


class CloudBackupTests(unittest.TestCase):
    def setUp(self):
        self.remote, self.settings, self.data = MemoryObjects(), MemoryConfiguration(), MemoryPersonalData()
        self.data.configuration = self.settings
        self.recovery = []
        self.now = datetime(2026, 10, 18, 10, tzinfo=timezone.utc)
        self.service = CloudBackupService(configuration=self.settings, personal_data=self.data,
            archive=PersonalBackupArchive(), store_factory=lambda *_: self.remote,
            recovery_store=lambda content: self.recovery.append(content) or "recovery.wlbackup", now=lambda: self.now)

    def test_uploads_use_remote_versions_and_enforce_count_and_age_retention(self):
        for index in range(3):
            result = self.service.upload()
            self.assertTrue(result.ok, result.error)
            self.now += timedelta(hours=1)
        overview = self.service.overview().value
        self.assertEqual(len(overview.versions), 2)
        self.assertEqual(len([key for key in self.remote.objects if key.startswith("objects/")]), 2)
        self.assertFalse(overview.remote_changed)
        self.now += timedelta(days=91)
        self.assertTrue(self.service.upload().ok)
        self.assertEqual(len(self.service.overview().value.versions), 1)
        self.settings.value["remote_revision"] = "another-device"
        self.assertEqual(self.service.upload().error.code, "cloud_conflict")
        current = self.service.overview().value.versions[0].revision
        self.assertTrue(self.service.upload(expected_revision=current, force=True).ok)

    def test_restore_checks_both_versions_and_preserves_a_local_recovery_archive(self):
        self.assertTrue(self.service.upload().ok)
        self.data.data = b"new local changes"
        overview = self.service.overview().value
        latest = overview.versions[0].revision
        options = dict(expected_revision=latest, expected_local_digest=overview.local_digest)
        self.assertEqual(self.service.download(latest, **options).error.code, "cloud_local_changed")
        restored = self.service.download(latest, force=True, **options)
        self.assertTrue(restored.ok, restored.error)
        self.assertEqual(self.data.data, b"personal data")
        self.assertEqual(PersonalBackupArchive().decode(self.recovery[0]), b"new local changes")
        self.assertEqual(restored.value.recovery_path, "recovery.wlbackup")
        self.assertTrue(self.service.upload().ok)
        self.assertEqual(self.service.download(latest, force=True, **options).error.code, "cloud_conflict")

    def test_concurrent_publication_fails_without_replacing_the_remote_head(self):
        self.assertTrue(self.service.upload().ok)
        before = self.remote.objects["head.json"]
        self.remote.race = lambda: self.remote.objects.__setitem__("head.json", before + b" ")
        self.assertEqual(self.service.upload().error.code, "cloud_conflict")
        self.assertEqual(self.remote.objects["head.json"], before + b" ")

    def test_backup_schedules_catch_up_without_repeating_the_same_calendar_period(self):
        for mode in ("daily", "weekly", "monthly", "interval"):
            configuration = replace(self.settings.configuration, schedule=mode, time="09:00", weekday=6, month_day=18)
            configuration.validate()
            self.assertTrue(backup_due(configuration, None, self.now))
            self.assertTrue(backup_due(configuration, self.now - timedelta(days=35), self.now))
            self.assertFalse(backup_due(configuration, self.now, self.now))
        with self.assertRaises(ValueError):
            replace(self.settings.configuration, endpoint="http://insecure.example").validate()

    def test_schedules_handle_month_ends_and_daylight_saving_transitions(self):
        zone = ZoneInfo("America/New_York")
        configuration = replace(self.settings.configuration, schedule="daily", time="02:30")
        previous = datetime(2026, 3, 7, 3, 30, tzinfo=zone)
        self.assertFalse(backup_due(configuration, previous, datetime(2026, 3, 8, 3, 29, tzinfo=zone)))
        self.assertTrue(backup_due(configuration, previous, datetime(2026, 3, 8, 3, 30, tzinfo=zone)))
        configuration = replace(configuration, time="01:30")
        first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
        self.assertFalse(backup_due(configuration, first, first.replace(fold=1)))
        monthly = replace(configuration, schedule="monthly", month_day=31, time="10:00")
        self.assertTrue(backup_due(monthly, datetime(2026, 1, 31, 10, tzinfo=zone), datetime(2026, 2, 28, 10, tzinfo=zone)))
        for endpoint in ("https://storage.example:invalid", "https://storage.example:65536", "https://storage.example:0"):
            with self.assertRaisesRegex(ValueError, "cloud_configuration_invalid"):
                replace(monthly, endpoint=endpoint).validate()

    def test_failed_retention_cleanup_is_recorded_and_retried_after_publication(self):
        self.settings.configuration = replace(self.settings.configuration, keep_count=1)
        self.assertTrue(self.service.upload().ok)
        original_delete = self.remote.delete
        self.remote.delete = lambda _key: (_ for _ in ()).throw(OSError("unavailable"))
        result = self.service.upload()
        self.assertTrue(result.ok, result.error)
        self.assertTrue(result.value.retention_pending)
        self.assertTrue(self.settings.value["pending_deletions"])
        self.remote.delete = original_delete
        self.assertTrue(self.service.upload().ok)
        self.assertEqual(self.settings.value["pending_deletions"], [])
        self.assertEqual(len(self.remote.objects), 2)

    def test_restore_rechecks_the_manifest_after_fetch_and_rejects_changed_content(self):
        self.assertTrue(self.service.upload().ok)
        overview = self.service.overview().value
        latest = overview.versions[0].revision
        original_get = self.remote.get
        def changed_head(key, *, limit):
            found = original_get(key, limit=limit)
            if key.startswith("objects/"):
                self.remote.objects["head.json"] += b" "
            return found
        self.remote.get = changed_head
        result = self.service.download(latest, expected_revision=latest, expected_local_digest=overview.local_digest)
        self.assertEqual(result.error.code, "cloud_conflict")
        self.assertEqual(self.recovery, [])
