from __future__ import annotations
from worklogger.infrastructure.database.migrations.runner import MIGRATION_VERSIONS

import base64
import json
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import sqlite3
import unittest
from unittest.mock import patch

from worklogger.app.commands.auth_commands import (
    ChangePasswordCommand,
    LoginCommand,
    RegisterUserCommand,
    ResetPasswordCommand,
)
from worklogger.app.commands.report_commands import SaveReportCommand
from worklogger.app.queries.analytics_queries import GetAnalyticsBundleQuery
from worklogger.app.queries.report_queries import GetReportForPeriodQuery
from worklogger.app.use_cases.analytics import GetAnalyticsBundleHandler
from worklogger.app.use_cases.auth import (
    ChangePasswordHandler,
    LoginHandler,
    LoginWithRememberTokenHandler,
    RegisterUserHandler,
    ResetPasswordHandler,
)
from worklogger.app.use_cases.reports import GetReportForPeriodHandler, SaveReportHandler
from worklogger.config.constants import LOCAL_MODEL_ACTIVE_ID_SETTING_KEY
from worklogger.domain.auth.models import LinkedIdentity
from worklogger.domain.calendar.models import CalendarEvent
from worklogger.domain.quicklog.models import QuickLog
from tests.quick_log_samples import insert_previous_entry
from worklogger.domain.worklog.models import EntryType, WorkLog
from worklogger.domain.worklog.rules import normalize_work_log
from worklogger.infrastructure.database import (
    MigrationRunner,
    SQLiteConnectionFactory,
    SQLiteUnitOfWork,
    default_database_path,
)
from worklogger.infrastructure.database.paths import prune_corrupt_backups
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
    SQLiteCalendarEventRepository,
    SQLiteIdentityRepository,
    SQLiteLoginFailureRepository,
    SQLiteQuickLogRepository,
    SQLiteReportRepository,
    SQLiteSettingsRepository,
    SQLiteWorkLogRepository,
)
from worklogger.infrastructure.security import (
    EncryptedSettingsKeyStore,
    FileRememberTokenSessionStore,
    FileMachineKeyProvider,
    FernetSecretBox,
    NoKeyringBackend,
    PBKDF2PasswordHasher,
)


class MemoryKeyringBackend:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, name: str) -> str | None:
        return self.values.get((service, name))

    def set_password(self, service: str, name: str, value: str) -> None:
        self.values[(service, name)] = value

    def delete_password(self, service: str, name: str) -> None:
        self.values.pop((service, name), None)


class SQLiteInfrastructureTests(unittest.TestCase):
    def test_expired_lock_cleanup_preserves_a_newer_failure_lock(self):
        now = datetime(2026, 10, 27, tzinfo=timezone.utc)
        for recovery in (False, True):
            with self.subTest(recovery=recovery):
                key = ("\0recovery:" if recovery else "") + "sample"
                with self.factory.transaction() as connection:
                    connection.execute("INSERT INTO login_attempts VALUES(?,?,?,?)", (
                        key, 4, (now - timedelta(seconds=1)).isoformat(),
                        (now - timedelta(minutes=1)).isoformat()))
                writer = SQLiteLoginFailureRepository(self.factory, clock=lambda: now, recovery=recovery)
                refreshed = []

                def clock():
                    if not refreshed:
                        refreshed.append(writer.record_failure("sample")[1])
                    return now

                reader = SQLiteLoginFailureRepository(self.factory, clock=clock, recovery=recovery)
                deadline = reader.lockout_until("sample")
                self.assertIsNotNone(deadline)
                self.assertEqual(deadline, refreshed[0])
                self.assertGreater(deadline, now)
                with self.factory.connection() as connection:
                    stored = connection.execute("SELECT failed_count,locked_until FROM login_attempts WHERE username=?",
                                                (key,)).fetchone()
                self.assertEqual(stored["failed_count"], 5)
                self.assertEqual(datetime.fromisoformat(stored["locked_until"]), deadline)

    def test_password_verification_rejects_malformed_stored_values(self):
        hasher = PBKDF2PasswordHasher(iterations=1000)
        password = hasher.hash_password("synthetic-password")
        for stored_hash, salt in ((password.hash_hex, "not-hex"), (password.hash_hex, ""),
                                  (password.hash_hex, None), ("not-a-hash", password.salt_hex),
                                  ("\u4e2d" * 64, password.salt_hex)):
            with self.subTest(stored_hash=stored_hash, salt=salt):
                self.assertFalse(hasher.verify("synthetic-password", stored_hash, salt).matched)
        self.assertTrue(hasher.verify("synthetic-password", password.hash_hex, password.salt_hex).matched)

    def test_encrypted_fallback_remains_authoritative_after_keyring_recovers(self):
        from unittest.mock import patch
        user = self.auth_repository().create_user("fallback-owner", "example-password", recovery_key=None, is_admin=False)
        backend = MemoryKeyringBackend()
        backend.values[("WorkLogger", "ai_api_key")] = "old-key"
        settings = SQLiteSettingsRepository(self.factory)
        store = EncryptedSettingsKeyStore(settings, user_id=user.id, keyring_backend=backend,
            secret_box=FernetSecretBox(FileMachineKeyProvider(Path(self._tempdir.name) / "key.bin")))
        with patch.object(backend, "set_password", side_effect=RuntimeError("unavailable")):
            self.assertTrue(store.set_secret("ai_api_key", "new-key").ok)
        self.assertEqual(store.get_secret("ai_api_key").value, "new-key")
        self.assertTrue(store.set_secret("ai_api_key", "latest-key").ok)
        self.assertIsNone(settings.get(user.id, "secret:ai_api_key"))
        self.assertEqual(store.get_secret("ai_api_key").value, "latest-key")

    def test_previous_machine_key_is_persisted_for_subsequent_reads(self):
        from unittest.mock import Mock
        path = Path(self._tempdir.name) / "persisted.key"
        loader = Mock(return_value=b"x" * 32)
        provider = FileMachineKeyProvider(path, loader)
        self.assertEqual(provider.load_or_create(), b"x" * 32)
        self.assertTrue(path.is_file())
        loader.side_effect = RuntimeError("unavailable")
        self.assertEqual(provider.load(), b"x" * 32)

    def test_missing_or_weakened_named_indexes_are_rejected_without_repairing_data(self):
        with self.factory.transaction() as connection:
            connection.execute("DROP INDEX idx_users_username_key")
            connection.execute("CREATE INDEX idx_users_username_key ON users(username_key)")
        with self.assertRaisesRegex(ValueError, "database_schema_unsupported"):
            MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            index = next(row for row in connection.execute("PRAGMA index_list(users)") if row[1] == "idx_users_username_key")
            self.assertEqual(index[2], 0)

    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.db_path = f"{self._tempdir.name}/worklog.db"
        self.factory = SQLiteConnectionFactory(self.db_path)
        self.assertEqual(MigrationRunner(self.factory).run_pending(), MIGRATION_VERSIONS)

    def auth_repository(self) -> SQLiteAuthRepository:
        return SQLiteAuthRepository(
            self.factory,
            password_hasher=PBKDF2PasswordHasher(
                iterations=1_000,
                legacy_iterations=(100,),
            ),
        )

    def test_invalid_collection_records_are_rejected_without_changing_storage(self) -> None:
        user = self.auth_repository().create_user("collection-user", "test-password", recovery_key=None, is_admin=False)
        day = date(2026, 5, 1)
        repository = SQLiteQuickLogRepository(self.factory)
        record_id = insert_previous_entry(self.factory, QuickLog(None, user.id, day, "Valid record")).id
        with self.factory.transaction(write=True) as connection:
            connection.execute("UPDATE quick_logs SET created_at='invalid' WHERE id=?", (record_id,))
            connection.execute("INSERT INTO worklog(user_id,d,\"break\",note,entry_type) VALUES(?, '2026-05-15X', 0, '', 'normal')", (user.id,))
            connection.execute("INSERT INTO worklog(user_id,d,\"break\",note,entry_type) VALUES(?, '2026-05-01', 0, '', 'normal')", (user.id,))
        with self.assertLogs("worklogger.infrastructure.repositories._mapping", level="WARNING"):
            with self.assertRaisesRegex(ValueError, "stored_work_logs_invalid"):
                SQLiteWorkLogRepository(self.factory).list_for_month(user.id, 2026, 5)
        with self.assertLogs("worklogger.infrastructure.repositories._mapping", level="WARNING"):
            quick_logs = repository.list_for_day(user.id, day)
        self.assertEqual(len(quick_logs), 1)
        self.assertIsNone(quick_logs[0].created_at)
        with self.assertLogs("worklogger.infrastructure.repositories._mapping", level="WARNING"):
            with self.assertRaisesRegex(ValueError, "stored_work_logs_invalid"):
                SQLiteWorkLogRepository(self.factory).list_export_rows(user.id)
        self.assertEqual(repository.list_for_day(user.id + 1, day), ())
        self.assertEqual(repository.list_for_range(user.id + 1, day, day), ())
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM worklog").fetchone()[0], 2)

    def test_password_hasher_verifies_legacy_iterations(self) -> None:
        hasher = PBKDF2PasswordHasher(iterations=1_000, legacy_iterations=(100,))
        salt_hex = "11" * 16
        legacy_hash = hasher.hash_with_salt("secret123", salt_hex, iterations=100)

        verification = hasher.verify("secret123", legacy_hash, salt_hex)

        self.assertTrue(verification.matched)
        self.assertTrue(verification.needs_upgrade)

    def test_selected_settings_reads_exclude_other_accounts_and_unrelated_drafts(self):
        user = self.auth_repository().create_user("settings-user", "synthetic-password", recovery_key=None, is_admin=False)
        other = self.auth_repository().create_user("other-settings", "synthetic-password", recovery_key=None, is_admin=False)
        settings = SQLiteSettingsRepository(self.factory)
        settings.set(user.id, "theme", "green")
        settings.set(user.id, "daily_note_draft:2026-10-11", "Private draft" * 1000)
        settings.set(other.id, "theme", "purple")
        self.assertEqual(settings.get_many(user.id, ("theme", "dark_mode", "theme")), {"theme": "green"})
        self.assertEqual(settings.get_many(user.id, ()), {})

    def test_migration_runner_is_idempotent_and_enables_foreign_keys(self) -> None:
        self.assertEqual(MigrationRunner(self.factory).run_pending(), ())
        with self.factory.connection() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("schema_migrations", tables)
            self.assertIn("users", tables)
            self.assertIn("worklog", tables)
            self.assertIn("activity_events", tables)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

        with SQLiteUnitOfWork(self.factory).transaction(write=False) as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                len(MIGRATION_VERSIONS),
            )

    def test_database_path_rules_for_source_and_frozen_modes(self) -> None:
        source_root = Path(self._tempdir.name) / "worklogger"
        exe_path = Path(self._tempdir.name) / "dist" / "WorkLogger.exe"
        user_path = Path(self._tempdir.name) / "user-data"

        self.assertEqual(
            default_database_path(frozen=False, package_root_path=source_root),
            source_root / "worklog.db",
        )
        self.assertEqual(
            default_database_path(frozen=True, executable=str(exe_path), user_data_path=user_path),
            user_path / "worklog.db",
        )

    def test_corrupt_database_is_quarantined_and_recreated(self) -> None:
        corrupt_path = Path(self._tempdir.name) / "corrupt.db"
        corrupt_path.write_bytes(b"not a sqlite database")
        factory = SQLiteConnectionFactory(corrupt_path, recover_corrupt=True, corrupt_backup_retention=2)

        self.assertEqual(MigrationRunner(factory).run_pending(), MIGRATION_VERSIONS)

        backups = sorted(corrupt_path.parent.glob("corrupt.db.bak_*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"not a sqlite database")
        with factory.connection() as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_corrupt_database_backups_are_pruned(self) -> None:
        database_path = Path(self._tempdir.name) / "retention.db"
        for index in range(4):
            backup = database_path.with_name(f"retention.db.bak_corrupt_{index}_{index:032x}")
            backup.write_text(str(index), encoding="utf-8")
            Path(str(backup) + "-wal").write_text("Retained journal", encoding="utf-8")
        unrelated = database_path.with_name("retention.db.bak_corrupt_personal-copy")
        unrelated.write_text("Retained original", encoding="utf-8")
        legacy = database_path.with_name("retention.db.bak_corrupt_123")
        legacy.write_text("Retained legacy copy", encoding="utf-8")

        prune_corrupt_backups(database_path, keep=2)

        recognized = list(database_path.parent.glob("retention.db.bak_corrupt_*_????????????????????????????????"))
        self.assertEqual(len(recognized), 2)
        self.assertEqual(len(list(database_path.parent.glob("retention.db.bak_corrupt_*-wal"))), 2)
        self.assertEqual(unrelated.read_text(encoding="utf-8"), "Retained original")
        self.assertEqual(legacy.read_text(encoding="utf-8"), "Retained legacy copy")

    def test_corrupt_backup_cleanup_does_not_remove_symbolic_links(self):
        database_path = Path(self._tempdir.name) / "retention.db"
        target = database_path.with_name("original-copy")
        target.write_text("Retained original", encoding="utf-8")
        link = database_path.with_name("retention.db.bak_corrupt_1_" + "a" * 32)
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symbolic links are unavailable")
        backup = database_path.with_name("retention.db.bak_corrupt_2_" + "b" * 32)
        backup.write_text("Retained backup", encoding="utf-8")
        prune_corrupt_backups(database_path, keep=1)
        self.assertTrue(link.is_symlink())
        self.assertTrue(backup.is_file())
        self.assertEqual(target.read_text(encoding="utf-8"), "Retained original")

    def test_corrupt_provenance_is_rejected_consistently_and_restore_rolls_back(self):
        user = self.auth_repository().create_user("report-owner", "example-password", recovery_key=None, is_admin=False)
        reports = SQLiteReportRepository(self.factory)
        day = date(2026, 10, 5)
        saved = SaveReportHandler(reports).handle(SaveReportCommand(user.id, "daily", day, day, "Original report")).value
        for raw in ('{', '[]', 'null', '{"sources":null}', '{"sources":[{}]}',
                    '{"sources":[1]}', '{"standard_hours":"invalid"}'):
            with self.subTest(provenance=raw):
                with self.factory.transaction() as connection:
                    connection.execute("UPDATE reports SET provenance=? WHERE id=?", (raw, saved.id))
                    connection.execute("UPDATE report_revisions SET provenance=? WHERE report_id=?", (raw, saved.id))
                operations = (
                    lambda: reports.get_by_id(user.id, saved.id),
                    lambda: reports.get_for_period(user.id, "daily", day, day),
                    lambda: reports.list_by_type(user.id, "daily"),
                    lambda: reports.list_revisions(user.id, saved.id),
                    lambda: reports.get_revision(user.id, saved.id, saved.revision),
                    lambda: reports.restore_revision(user.id, saved.id, saved.revision, saved.revision),
                )
                for operation in operations:
                    with self.assertRaisesRegex(ValueError, "^stored_records_invalid$"):
                        operation()
                with self.factory.connection() as connection:
                    self.assertEqual(tuple(connection.execute("SELECT revision,content,provenance FROM reports WHERE id=?",
                                                              (saved.id,)).fetchone()), (saved.revision, saved.content, raw))
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM report_revisions WHERE report_id=?",
                                                        (saved.id,)).fetchone()[0], 1)

    def test_provenance_preserves_known_fields_and_accepts_additional_metadata(self):
        from worklogger.infrastructure.repositories.report_provenance_sqlite import decode_provenance
        value = {"language": "en", "future_metadata": {"version": 2}, "sources": [
            {"kind": "record", "identifier": "41", "revision": 2, "digest": "source-digest", "future_field": True}]}
        decoded = decode_provenance(json.dumps(value))
        self.assertEqual((decoded.language, decoded.standard_hours), ("en", 8.0))
        self.assertEqual((decoded.sources[0].identifier, decoded.sources[0].revision), ("41", 2))
        self.assertEqual(decode_provenance("{}").sources, ())

    def test_atomic_destination_syncs_published_files_and_preserves_existing_destinations(self):
        from worklogger.infrastructure.files import atomic_destination
        destination = Path(self._tempdir.name) / "export.json"
        for overwrite in (True, False):
            with self.subTest(overwrite=overwrite):
                destination.unlink(missing_ok=True)
                def directory_synced(directory):
                    self.assertEqual(directory, destination.parent)
                    self.assertEqual(destination.read_bytes(), b"Complete export")
                with patch("worklogger.infrastructure.files._sync_directory", side_effect=directory_synced) as sync:
                    with atomic_destination(destination, overwrite=overwrite) as temporary:
                        temporary.write_bytes(b"Complete export")
                sync.assert_called_once_with(destination.parent)
                self.assertFalse(temporary.exists())
        with self.assertRaises(FileExistsError):
            with atomic_destination(destination, overwrite=False) as temporary:
                temporary.write_bytes(b"Replacement")
        self.assertEqual(destination.read_bytes(), b"Complete export")
        self.assertFalse(temporary.exists())

    def test_directory_sync_closes_its_descriptor_even_when_sync_fails(self):
        from worklogger.infrastructure.files import _sync_directory
        with patch("worklogger.infrastructure.files.os.name", "posix"), \
                patch("worklogger.infrastructure.files.os.open", return_value=17) as opened, \
                patch("worklogger.infrastructure.files.os.close") as closed, \
                patch("worklogger.infrastructure.files.os.fsync", side_effect=OSError("Storage failure")):
            with self.assertRaises(OSError):
                _sync_directory(self._tempdir.name)
        opened.assert_called_once()
        closed.assert_called_once_with(17)

    def test_database_access_failure_preserves_existing_data(self) -> None:
        path = Path(self._tempdir.name) / "locked.db"
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE records(value TEXT)")
            connection.execute("INSERT INTO records VALUES('retained')")
            connection.commit()
        reader = sqlite3.connect(path)
        self.addCleanup(reader.close)
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM records").fetchall()
        factory = SQLiteConnectionFactory(path, busy_timeout_ms=10, recover_corrupt=True)
        with self.assertRaises(sqlite3.OperationalError):
            factory.open()
        self.assertFalse(list(path.parent.glob("locked.db.bak_*")))
        self.assertEqual(reader.execute("SELECT value FROM records").fetchone()[0], "retained")

    def test_unknown_schema_version_is_rejected_without_changes(self) -> None:
        with self.factory.transaction() as connection:
            connection.execute("INSERT INTO schema_migrations VALUES(9999, 'future_schema', '2026-01-01')")
        with self.assertRaisesRegex(ValueError, "database_version_unsupported"):
            MigrationRunner(self.factory).run_pending()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 9999)

    def test_auth_handlers_use_sqlite_repository_and_hashed_remember_tokens(self) -> None:
        auth = self.auth_repository()
        failures = SQLiteLoginFailureRepository(self.factory)
        registered = RegisterUserHandler(auth).handle(
            RegisterUserCommand("alice", "secret123")
        )
        self.assertTrue(registered.ok)
        assert registered.value is not None
        self.assertTrue(registered.value.user.is_admin)

        duplicate = RegisterUserHandler(auth).handle(
            RegisterUserCommand("alice", "secret456")
        )
        self.assertFalse(duplicate.ok)
        self.assertEqual(duplicate.error.code if duplicate.error else "", "username_exists")

        logged_in = LoginHandler(auth, failures).handle(
            LoginCommand("alice", "secret123", remember=True)
        )
        self.assertTrue(logged_in.ok)
        assert logged_in.value is not None
        self.assertTrue(logged_in.value.token)
        with self.factory.connection() as connection:
            row = connection.execute(
                "SELECT remember_token FROM users WHERE username='alice'"
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["remember_token"], logged_in.value.token)
        self.assertTrue(str(row["remember_token"]).startswith("sha256:"))

        remembered = LoginWithRememberTokenHandler(auth).handle(logged_in.value.token or "")
        self.assertTrue(remembered.ok)
        assert remembered.value is not None
        self.assertEqual(remembered.value.username, "alice")
        from worklogger.app.use_cases.auth import RevokeRememberedSessionHandler
        self.assertTrue(RevokeRememberedSessionHandler(auth, user_id=registered.value.user.id).handle().ok)
        self.assertFalse(LoginWithRememberTokenHandler(auth).handle(logged_in.value.token or "").ok)

        changed = ChangePasswordHandler(auth).handle(
            ChangePasswordCommand(registered.value.user.id, "secret123", "secret456")
        )
        self.assertTrue(changed.ok)
        self.assertFalse(LoginHandler(auth, failures).handle(LoginCommand("alice", "secret123")).ok)
        self.assertTrue(LoginHandler(auth, failures).handle(LoginCommand("alice", "secret456")).ok)

        reset = ResetPasswordHandler(auth).handle(
            ResetPasswordCommand("alice", changed.value or "", "secret789")
        )
        self.assertTrue(reset.ok)
        self.assertTrue(LoginHandler(auth, failures).handle(LoginCommand("alice", "secret789")).ok)

    def test_login_failures_lock_out_after_threshold(self) -> None:
        auth = self.auth_repository()
        failures = SQLiteLoginFailureRepository(self.factory)
        RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))

        for _ in range(5):
            self.assertFalse(
                LoginHandler(auth, failures).handle(LoginCommand("alice", "wrong")).ok
            )

        blocked = LoginHandler(auth, failures).handle(LoginCommand("alice", "secret123"))
        self.assertFalse(blocked.ok)
        self.assertEqual(blocked.error.code if blocked.error else "", "account_locked")

    def test_worklog_quicklog_settings_report_and_analytics_repositories(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id

        work_logs = SQLiteWorkLogRepository(self.factory)
        saved_work_log = work_logs.save_entry(normalize_work_log(
            WorkLog(
                user_id=user_id,
                day=date(2026, 4, 20),
                start_time="2200",
                end_time="0900",
                break_hours=1.0,
                note="Night shift",
                entry_type=EntryType.NORMAL.value,
            )
        ))
        self.assertIsNotNone(saved_work_log.id)
        fetched = work_logs.get_for_day(user_id, date(2026, 4, 20))
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertTrue(fetched.overnight)
        self.assertEqual(fetched.worked_hours(), 10.0)

        work_logs.import_many((
            WorkLog(
                user_id=user_id,
                day=date(2026, 4, 21),
                start_time=None,
                end_time=None,
                break_hours=0.0,
                note="Leave",
                entry_type=EntryType.PAID_LEAVE,
            ),
        ))
        analytics = GetAnalyticsBundleHandler(work_logs).handle(
            GetAnalyticsBundleQuery(
                user_id=user_id,
                year=2026,
                month=4,
                metric="hours",
                include_leaves=True,
            )
        )
        self.assertTrue(analytics.ok)
        assert analytics.value is not None
        self.assertEqual(analytics.value.leave_line_data[3], 8.0)

        quick_logs = SQLiteQuickLogRepository(self.factory)
        insert_previous_entry(self.factory, QuickLog(None, user_id, date(2026, 4, 20), "Meeting", "09:30", "10:00"))
        listed = quick_logs.list_for_range(user_id, date(2026, 4, 1), date(2026, 4, 30))
        self.assertEqual(len(listed), 1)

        settings = SQLiteSettingsRepository(self.factory)
        settings.set(user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, "model-a")
        self.assertEqual(settings.get(user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY), "model-a")

        reports = SQLiteReportRepository(self.factory)
        saved_report = SaveReportHandler(reports).handle(
            SaveReportCommand(
                user_id=user_id,
                report_type="weekly",
                period_start=date(2026, 4, 20),
                period_end=date(2026, 4, 26),
                content="weekly report",
            )
        )
        self.assertTrue(saved_report.ok)
        fetched_report = GetReportForPeriodHandler(reports).handle(
            GetReportForPeriodQuery(
                user_id=user_id,
                report_type="weekly",
                period_start=date(2026, 4, 20),
                period_end=date(2026, 4, 26),
            )
        )
        self.assertEqual(fetched_report.value, saved_report.value)

    def test_calendar_and_identity_repositories(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id

        calendar = SQLiteCalendarEventRepository(self.factory)
        count = calendar.replace_all(
            user_id,
            (
                CalendarEvent(
                    id=None,
                    user_id=user_id,
                    day=date(2026, 4, 20),
                    summary="Planning",
                    start_time="09:00",
                    end_time="10:00",
                ),
            ),
        )
        self.assertEqual(count, 1)
        self.assertEqual(calendar.list_for_day(user_id, date(2026, 4, 20))[0].summary, "Planning")

        identities = SQLiteIdentityRepository(self.factory)
        identity = identities.add(
            LinkedIdentity(
                id=0,
                user_id=user_id,
                provider="google",
                subject="subject-1",
                email="alice@example.com",
            )
        )
        self.assertEqual(identities.list_for_user(user_id), (identity,))
        identities.remove(user_id, identity.id)
        self.assertEqual(identities.list_for_user(user_id), ())

    def test_encrypted_key_store_uses_keyring_when_available(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id
        settings = SQLiteSettingsRepository(self.factory)
        keyring = MemoryKeyringBackend()
        store = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=keyring,
        )

        result = store.set_secret("ai_api_key", "super-secret")

        self.assertTrue(result.ok)
        self.assertEqual(store.get_secret("ai_api_key").value, "super-secret")
        self.assertIsNone(settings.get(user_id, "secret:ai_api_key"))
        self.assertIn(("WorkLogger", "ai_api_key"), keyring.values)

    def test_encrypted_key_store_falls_back_to_encrypted_settings(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id
        settings = SQLiteSettingsRepository(self.factory)
        key_path = Path(self._tempdir.name) / "machine.key"
        secret_box = FernetSecretBox(FileMachineKeyProvider(key_path))
        store = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=NoKeyringBackend(),
            secret_box=secret_box,
        )

        result = store.set_secret("ai_api_key", "super-secret")

        self.assertTrue(result.ok)
        stored = settings.get(user_id, "secret:ai_api_key")
        self.assertIsNotNone(stored)
        self.assertTrue(str(stored).startswith("enc2:"))
        self.assertNotIn("super-secret", str(stored))

        reopened = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=NoKeyringBackend(),
            secret_box=FernetSecretBox(FileMachineKeyProvider(key_path)),
        )
        self.assertEqual(reopened.get_secret("ai_api_key").value, "super-secret")
        self.assertTrue(key_path.exists())

        deleted = reopened.delete_secret("ai_api_key")
        self.assertTrue(deleted.ok)
        self.assertIsNone(settings.get(user_id, "secret:ai_api_key"))

    def test_encrypted_key_store_rejects_tampered_ciphertext(self) -> None:
        auth = self.auth_repository()
        registered = RegisterUserHandler(auth).handle(RegisterUserCommand("alice", "secret123"))
        assert registered.value is not None
        user_id = registered.value.user.id
        settings = SQLiteSettingsRepository(self.factory)
        key_path = Path(self._tempdir.name) / "machine.key"
        store = EncryptedSettingsKeyStore(
            settings,
            user_id=user_id,
            keyring_backend=NoKeyringBackend(),
            secret_box=FernetSecretBox(FileMachineKeyProvider(key_path)),
        )
        self.assertTrue(store.set_secret("ai_api_key", "super-secret").ok)
        stored = settings.get(user_id, "secret:ai_api_key") or ""
        prefix = "enc2:"
        payload = bytearray(base64.urlsafe_b64decode(stored[len(prefix) :].encode("ascii")))
        payload[-1] ^= 0x01
        tampered = prefix + base64.urlsafe_b64encode(bytes(payload)).decode("ascii")
        settings.set(user_id, "secret:ai_api_key", tampered)

        result = store.get_secret("ai_api_key")

        self.assertFalse(result.ok)
        self.assertEqual(result.error.code if result.error else "", "secret_authentication_failed")

    def test_file_remember_token_store_encrypts_loads_and_clears_token(self) -> None:
        token_path = Path(self._tempdir.name) / "remember_session.enc"
        key_path = Path(self._tempdir.name) / "machine.key"
        store = FileRememberTokenSessionStore(
            token_path,
            secret_box=FernetSecretBox(FileMachineKeyProvider(key_path)),
        )

        saved = store.save_token("plain-token")

        self.assertTrue(saved.ok, saved.error)
        self.assertTrue(token_path.exists())
        self.assertNotIn("plain-token", token_path.read_text(encoding="utf-8"))
        self.assertEqual(store.load_token().value, "plain-token")

        cleared = store.clear_token()

        self.assertTrue(cleared.ok, cleared.error)
        self.assertFalse(token_path.exists())
        self.assertIsNone(store.load_token().value)

    def test_credentials_upgrade_older_ciphertext_and_preserve_invalid_keys(self):
        from cryptography.fernet import Fernet
        key_path = Path(self._tempdir.name) / "machine.key"
        key_path.write_text(base64.urlsafe_b64encode(bytes(range(32))).decode("ascii"), encoding="ascii")
        token_path = Path(self._tempdir.name) / "remember_session.enc"
        released = "enc1:" + Fernet(base64.urlsafe_b64encode(bytes(range(32)))).encrypt(b"compatibility-token").decode("ascii")
        token_path.write_text(released, encoding="ascii")
        store = FileRememberTokenSessionStore(token_path, secret_box=FernetSecretBox(FileMachineKeyProvider(key_path)))
        self.assertEqual(store.load_token().value, "compatibility-token")
        self.assertTrue(token_path.read_text().startswith("enc2:"))
        key_path.write_text("invalid key", encoding="ascii")
        self.assertFalse(store.load_token().ok)
        self.assertFalse(store.save_token("replacement").ok)
        self.assertEqual(key_path.read_text(), "invalid key")
        key_path.unlink()
        self.assertFalse(store.load_token().ok)
        self.assertFalse(key_path.exists())

    def test_login_failure_retention_and_successful_login_time(self):
        auth = self.auth_repository()
        user = auth.create_user("alice", "secret123", recovery_key=None, is_admin=True)
        now = datetime(2026, 5, 1, tzinfo=timezone.utc)
        with patch.object(self.factory, "transaction", side_effect=AssertionError("unexpected write transaction")):
            failures = SQLiteLoginFailureRepository(self.factory, clock=lambda: now)
            failures.prune()
        self.assertEqual(failures.record_failure("unknown"), (1, None))
        for _ in range(4):
            failures.record_failure("unknown")
        self.assertIsNotNone(failures.lockout_until("unknown"))
        with patch("worklogger.infrastructure.repositories.login_failures_sqlite._MAX_UNKNOWN_ATTEMPTS", 2):
            for name in ("missing-one", "missing-two", "missing-three"):
                failures.record_failure(name)
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0], 2)
        for _ in range(4):
            failures.record_failure("alice")
        now += timedelta(days=2)
        self.assertEqual(failures.record_failure("alice"), (1, None))
        now += timedelta(days=8)
        failures.prune()
        with self.factory.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM login_attempts").fetchone()[0], 0)
        logged_in = auth.verify_user("alice", "secret123")
        self.assertIsNotNone(logged_in.last_login_at)
        self.assertEqual(auth.get_by_id(user.id).last_login_at, logged_in.last_login_at)


if __name__ == "__main__":
    unittest.main()
