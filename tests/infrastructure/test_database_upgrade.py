from contextlib import closing
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import base64
import hashlib
import platform
import uuid
import json
from cryptography.fernet import Fernet

from tests.infrastructure.schema_samples import SCHEMAS
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.repositories import SQLiteAuthRepository, SQLiteSettingsRepository, SQLiteWorkLogRepository, SQLiteIdentityRepository
from worklogger.infrastructure.security import PBKDF2PasswordHasher
from worklogger.domain.auth.models import LinkedIdentity
from worklogger.domain.worklog.models import EntryType, WorkMode
from worklogger.infrastructure.security.key_store import EncryptedSettingsKeyStore, FileMachineKeyProvider, FernetSecretBox, NoKeyringBackend
from worklogger.infrastructure.database.upgrade import upgrade_database
from worklogger.infrastructure.database.migrations.runner import MIGRATION_VERSIONS


class DatabaseUpgradeTests(unittest.TestCase):
    def test_versioned_accounts_upgrade_transactionally_without_changing_record_identifiers(self):
        from worklogger.infrastructure.database.current_schema import TABLE_STATEMENTS, INDEX_STATEMENTS, CURRENT_SCHEMA_VERSION
        from tests.infrastructure.test_work_mode_migration import WORKLOG_VERSION_17
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "previous.db"
            factory = SQLiteConnectionFactory(path)
            with factory.transaction() as connection:
                for table, statement in TABLE_STATEMENTS.items():
                    if table == "worklog":
                        statement = WORKLOG_VERSION_17.replace("work_mode TEXT CHECK", "work_mode_label TEXT NOT NULL DEFAULT '', work_mode TEXT CHECK")
                    connection.execute(statement)
                for statement in INDEX_STATEMENTS:
                    if "work_items_owner_project" not in statement:
                        connection.execute(statement)
                connection.execute("INSERT INTO schema_migrations VALUES(18,'entry_classification_and_work_modes','2026-10-18')")
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            user = auth.create_user("previous-owner", "example-password", recovery_key=None, is_admin=True)
            with factory.transaction() as connection:
                connection.execute("INSERT INTO worklog(id,user_id,d,start,end) VALUES(77,?,'2026-10-18','09:00','10:00')", (user.id,))
            self.assertEqual(MigrationRunner(factory).run_pending(), (CURRENT_SCHEMA_VERSION,))
            self.assertEqual(SQLiteWorkLogRepository(factory).list_all(user.id)[0].id, 77)
            self.assertEqual(auth.verify_user(user.username, "example-password").id, user.id)
            self.assertEqual(MigrationRunner(factory).run_pending(), ())
            self.assertEqual(len(list(Path(directory).glob("*.bak_upgrade_*"))), 1)

    def test_google_binding_upgrade_preserves_account_identity_and_blocks_unknown_bindings(self):
        from worklogger.app.commands.identity_commands import LoginWithIdentityCommand
        from worklogger.app.use_cases.identity import LoginWithIdentityHandler
        from worklogger.domain.identity.models import ExternalIdentityProfile
        from worklogger.domain.shared.result import Result
        from unittest.mock import Mock
        for subject in ("123456789", "https://accounts.google.com/123456789", None):
            with self.subTest(subject=subject), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "accounts.db"
                self.create_source(path, SCHEMAS[-1])
                with closing(sqlite3.connect(path)) as connection, connection:
                    connection.execute("INSERT INTO external_identities(id,user_id,provider,broker,issuer,subject,"
                        "federated_subject,created_at,updated_at) VALUES(51,17,'google','firebase',"
                        "'https://securetoken.google.com/example','firebase-uid',?,'2026-01-01','2026-01-01')", (subject,))
                factory = SQLiteConnectionFactory(path)
                MigrationRunner(factory).run_pending()
                identities = SQLiteIdentityRepository(factory)
                auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
                provider = Mock(provider_id="google")
                provider.authenticate.return_value = Result.success(ExternalIdentityProfile(
                    "google", "123456789", issuer="https://accounts.google.com"))
                result = LoginWithIdentityHandler(identities=identities, auth=auth, providers=(provider,)).handle(
                    LoginWithIdentityCommand("google"))
                if subject:
                    self.assertTrue(result.ok, result.error)
                    self.assertEqual((result.value.user.id, result.value.linked_identity.id), (17, 51))
                else:
                    self.assertEqual(result.error.code, "identity_relink_required")
                self.assertEqual(auth.user_count(), 1)
                with factory.transaction() as connection:
                    with self.assertRaises(sqlite3.IntegrityError):
                        connection.execute("INSERT INTO external_identities(user_id,provider,broker,issuer,subject,created_at,updated_at) "
                            "SELECT user_id,provider,'other','other',subject,created_at,updated_at FROM external_identities WHERE id=51")

    def test_upgrade_retains_snapshots_on_failure_and_bounds_them_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.db"
            self.create_source(path, SCHEMAS[1])
            for number in range(5):
                path.with_name(f"source.db.bak_upgrade_20200101T00000{number}Z_{uuid.uuid4().hex}").write_bytes(b"previous snapshot")
            manual = path.with_name("source.db.bak_manual")
            manual.write_bytes(b"manual backup")
            other = path.with_name(f"other.db.bak_upgrade_20200101T000000Z_{uuid.uuid4().hex}")
            other.write_bytes(b"other database")
            factory = SQLiteConnectionFactory(path)
            with patch("worklogger.infrastructure.database.migrations.runner.import_released_schema", side_effect=OSError("unavailable")):
                with self.assertRaises(OSError):
                    MigrationRunner(factory).run_pending()
            self.assertEqual(len(list(path.parent.glob("source.db.bak_upgrade_*"))), 6)
            MigrationRunner(factory).run_pending()
            self.assertEqual(len(list(path.parent.glob("source.db.bak_upgrade_*"))), 3)
            self.assertEqual(manual.read_bytes(), b"manual backup")
            self.assertEqual(other.read_bytes(), b"other database")

    def test_unversioned_development_layout_is_rejected_without_changing_data(self):
        from datetime import date
        from worklogger.domain.worklog.models import WorkLog
        from worklogger.app.use_cases.entry_types import EntryTypeService
        from worklogger.infrastructure.repositories.entry_type_sqlite import SQLiteEntryTypeRepository
        from worklogger.infrastructure.repositories.note_sqlite import SQLiteDailyNoteRepository
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(Path(directory) / "current.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            user = auth.create_user("sample", "example-password", recovery_key=None, is_admin=False)
            auth.set_display_name(user.id, "Mary", expected_display_name="")
            types = EntryTypeService(user.id, SQLiteEntryTypeRepository(factory))
            definition = types.save("Research", "work").value
            records = SQLiteWorkLogRepository(factory)
            day = date(2026, 5, 20)
            first = records.save_entry(WorkLog(user.id, day, "09:00", "10:00", note="Entry content", entry_type=definition))
            edited = records.save_entry(replace(first, note="Revised content"))
            second = records.save_entry(WorkLog(user.id, day, "10:00", "11:00", note="Another period"))
            with factory.transaction() as connection:
                connection.execute("INSERT INTO daily_notes(user_id,d,content) VALUES(?,?,?)", (user.id, day.isoformat(), "Independent memo"))
                connection.execute("DROP TABLE schema_migrations")
            with self.assertRaisesRegex(ValueError, "database_schema_unsupported"):
                MigrationRunner(factory).run_pending()
            self.assertEqual(auth.get_by_id(user.id).display_name, "Mary")
            self.assertEqual(records.list_for_day(user.id, day), (edited, second))
            self.assertEqual(types.list_types().value, (definition,))
            self.assertEqual(SQLiteDailyNoteRepository(factory).get_for_day(user.id, day).content, "Independent memo")
            self.assertFalse(list(Path(directory).glob("*.bak_upgrade_*")))

    def test_explicit_upgrade_keeps_source_and_publishes_only_complete_results(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"source.db", Path(directory)/"updated.db"
            self.create_source(source, SCHEMAS[1])
            original = source.read_bytes()
            with patch("worklogger.infrastructure.database.migrations.runner.import_released_schema", side_effect=OSError("interrupted upgrade")):
                with self.assertRaises(OSError):
                    upgrade_database(source, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(source.read_bytes(), original)
            report = upgrade_database(source,destination)
            self.assertEqual((report.accounts,report.time_records,report.reports),(1,2,1))
            self.assertEqual(report.applied_versions, MIGRATION_VERSIONS)
            self.assertEqual(source.read_bytes(),original)
            result = destination.read_bytes()
            with self.assertRaisesRegex(ValueError,"database_destination_exists"):
                upgrade_database(source,destination)
            self.assertEqual(destination.read_bytes(),result)
            self.assertFalse(list(Path(directory).glob(".*.bak_upgrade_*")))
            template = Path(directory)/"personal.json"
            template.write_text(json.dumps({"name":"Personal","type":"daily","content":"# Custom {{date}}"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"template_import_user_missing"):
                upgrade_database(source,Path(directory)/"failed-template.db",template_file=template,template_user="unknown")
            self.assertFalse((Path(directory)/"failed-template.db").exists())
            target = Path(directory)/"with-template.db"
            upgrade_database(source,target,template_file=template,template_user="ExistingUser",template_language="ja_JP")
            with closing(sqlite3.connect(target)) as connection:
                self.assertEqual(tuple(connection.execute("SELECT user_id,language,type,content FROM report_templates").fetchone()),
                                 (17,"ja_JP","daily","# Custom {{date}}"))

    def test_previous_credential_formats_require_authentication_before_replacement(self):
        for deterministic in (False, True):
            with self.subTest(deterministic=deterministic), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/"credentials.db"
                self.create_source(path, SCHEMAS[0])
                factory = SQLiteConnectionFactory(path)
                MigrationRunner(factory).run_pending()
                settings = SQLiteSettingsRepository(factory)
                key_provider = FileMachineKeyProvider(Path(directory)/"key")
                current_key = key_provider.load_or_create()
                previous_key = hashlib.sha256(f"{platform.node()}|{uuid.getnode()}".encode()).digest() if deterministic else current_key
                encoded = "enc1:" + Fernet(base64.urlsafe_b64encode(previous_key)).encrypt(b"example-secret").decode()
                settings.set(17,"ai_api_key",encoded)
                store = EncryptedSettingsKeyStore(settings,user_id=17,keyring_backend=NoKeyringBackend(),secret_box=FernetSecretBox(key_provider))
                result = store.get_secret("ai_api_key")
                if deterministic:
                    self.assertFalse(result.ok)
                    self.assertEqual(settings.get(17,"ai_api_key"), encoded)
                    self.assertIsNone(settings.get(17,"secret:ai_api_key"))
                    self.assertEqual(key_provider.load(), current_key)
                    continue
                self.assertTrue(result.ok,result.error)
                self.assertEqual(result.value,"example-secret")
                self.assertIsNone(settings.get(17,"ai_api_key"))
                upgraded = settings.get(17,"secret:ai_api_key")
                self.assertTrue(upgraded.startswith("enc2:"))
                self.assertNotIn("example-secret",upgraded)
                settings.delete(17,"secret:ai_api_key")
                damaged = encoded[:-8] + "AAAAAAAA"
                settings.set(17,"ai_api_key",damaged)
                self.assertFalse(store.get_secret("ai_api_key").ok)
                self.assertEqual(settings.get(17,"ai_api_key"),damaged)

    def create_source(self, path, schema):
        with closing(sqlite3.connect(path)) as connection:
            for statement in schema:
                connection.execute(statement)
            password = PBKDF2PasswordHasher(iterations=1000).hash_password("example-password")
            connection.execute("INSERT INTO users(id,username,password_hash,salt,is_admin,created_at,password_changed_at) VALUES(?,?,?,?,1,?,?)",
                (17, "ExistingUser", password.hash_hex, password.salt_hex, "2026-05-01T09:00:00+00:00", "2026-05-01T09:00:00+00:00"))
            connection.execute('INSERT INTO worklog(user_id,d,start,end,"break",note,work_type,overnight) VALUES(17,?,?,?,?,?,?,?)',
                ("2026-05-14", "22:00", "06:00", 1, "Original work", "remote", 1))
            connection.execute('INSERT INTO worklog(user_id,d,start,end,"break",note,work_type,overnight) VALUES(17,?,?,?,?,?,?,?)',
                ("2026-05-15", "09:00", "10:00", None, None, None, None))
            connection.executemany("INSERT INTO settings VALUES(17,?,?)", (("lang","ja_JP"),("dark","1"),
                ("work_hours","7.5"),("default_lunch","0.75"),("monthly_target","150"),("force_password_change","1")))
            connection.execute("INSERT INTO reports VALUES(42,17,'daily','2026-05-14','2026-05-14','Saved report','2026-05-14T07:00:00Z')")
            if any("oauth_identities" in statement for statement in schema):
                connection.execute("INSERT INTO oauth_identities VALUES(31,17,'google','subject','user@example.test','Name','2026-05-01','2026-05-01')")
            connection.commit()
        return password

    def test_released_schemas_preserve_accounts_records_preferences_and_one_snapshot(self):
        for schema in SCHEMAS:
            with self.subTest(schema=len(schema)), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/"source.db"
                password = self.create_source(path, schema)
                factory = SQLiteConnectionFactory(path)
                self.assertEqual(MigrationRunner(factory).run_pending(), MIGRATION_VERSIONS)
                backups = list(path.parent.glob("*.bak_upgrade_*"))
                self.assertEqual(len(backups), 1)
                auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
                user = auth.verify_user("existinguser", "example-password")
                self.assertEqual(user.id, 17)
                self.assertTrue(user.is_admin)
                self.assertTrue(user.must_change_password)
                settings = SQLiteSettingsRepository(factory)
                for key, expected in (("language","ja_JP"),("dark_mode","1"),("standard_work_hours","7.5"),("default_break_hours","0.75"),("monthly_target_hours","150")):
                    self.assertEqual(settings.get(17,key),expected)
                records = SQLiteWorkLogRepository(factory).list_all(17)
                self.assertEqual(records[0].worked_hours(),7)
                self.assertEqual(records[1].worked_hours(),1)
                self.assertEqual(records[0].note,"Original work")
                self.assertEqual(records[0].entry_type, EntryType.REMOTE)
                self.assertEqual(records[0].work_mode, WorkMode.REMOTE)
                self.assertIsNone(records[1].work_mode)
                identities = SQLiteIdentityRepository(factory)
                linked = identities.add(LinkedIdentity(0,17,"google","new-subject"))
                self.assertEqual(linked.user_id,17)
                if any("oauth_identities" in statement for statement in schema):
                    self.assertEqual(identities.get_by_provider_subject("google","subject").user_id,17)
                with factory.connection() as connection:
                    self.assertEqual(connection.execute("SELECT content FROM reports WHERE id=42").fetchone()[0],"Saved report")
                    self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(),[])
                    self.assertEqual(connection.execute("SELECT password_hash FROM users WHERE id=17").fetchone()[0],password.hash_hex)
                with patch("worklogger.infrastructure.database.migrations.runner.save_snapshot", side_effect=AssertionError("unexpected snapshot")):
                    self.assertEqual(MigrationRunner(factory).run_pending(),())
                with closing(sqlite3.connect(backups[0])) as backup:
                    self.assertIn("salt",{row[1] for row in backup.execute("PRAGMA table_info(users)")})
                    self.assertEqual(backup.execute("SELECT COUNT(*) FROM worklog").fetchone()[0],2)
                    self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0],"ok")

    def test_released_classifications_and_note_only_rows_preserve_historical_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "released.db"
            self.create_source(path, SCHEMAS[-1])
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.executemany('INSERT INTO worklog(user_id,d,start,end,"break",note,work_type,overnight) VALUES(17,?,?,?,?,?,?,0)', (
                    ("2026-05-16", "09:00", "11:00", 0.5, "Trip", "business_trip"),
                    ("2026-05-17", None, None, 0, "Leave", "paid_leave"),
                    ("2026-05-18", "12:00", "12:30", 0, "Break", "break"),
                    ("2026-05-19", None, None, 0, "Memo", "normal"),
                    ("2026-05-20", None, None, 0, "", "normal"),
                ))
            factory = SQLiteConnectionFactory(path)
            MigrationRunner(factory).run_pending()
            records = SQLiteWorkLogRepository(factory).list_all(17)
            self.assertEqual(len(records), 6)
            trip, leave, pause, empty = records[2:]
            self.assertEqual((trip.entry_type, trip.work_mode, trip.worked_hours()),
                             (EntryType.BUSINESS_TRIP, WorkMode.BUSINESS_TRIP, 1.5))
            self.assertFalse(leave.has_times)
            self.assertEqual((leave.worked_hours(), leave.leave_hours(), leave.work_mode), (0, 8, None))
            self.assertEqual((pause.worked_hours(), pause.raw_hours(), pause.work_mode), (0, 0.5, None))
            self.assertFalse(empty.has_times)
            self.assertEqual(empty.entry_type, EntryType.NORMAL)
            with factory.connection() as connection:
                self.assertEqual(connection.execute("SELECT content FROM daily_notes WHERE d='2026-05-19'").fetchone()[0], "Memo")
            self.assertEqual(MigrationRunner(factory).run_pending(), ())

    def test_invalid_released_records_roll_back_and_unknown_types_fail_before_writes(self):
        cases = (("d", "2026-02-30"), ("start", "25:00"), ("end", None),
                 ("break", -1), ("break", 8), ("break", float("inf")),
                 ("work_type", "unknown"), ("work_type", ""))
        for column, value in cases:
            with self.subTest(column=column, value=value), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "invalid.db"
                self.create_source(path, SCHEMAS[-1])
                with closing(sqlite3.connect(path)) as connection, connection:
                    connection.execute(f'UPDATE worklog SET "{column}"=? WHERE d=?', (value, "2026-05-14"))
                    original = tuple(connection.execute("SELECT * FROM worklog ORDER BY d"))
                factory = SQLiteConnectionFactory(path)
                expected = "database_entry_type_unsupported" if column == "work_type" else "database_record_invalid"
                with self.assertRaisesRegex(ValueError, expected):
                    MigrationRunner(factory).run_pending()
                with closing(sqlite3.connect(path)) as connection:
                    self.assertEqual(tuple(connection.execute("SELECT * FROM worklog ORDER BY d")), original)
                    self.assertIn("salt", {row[1] for row in connection.execute("PRAGMA table_info(users)")})
                    self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='worklog_import'").fetchone())
                    self.assertIsNone(connection.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone())
                self.assertEqual(len(list(Path(directory).glob("*.bak_upgrade_*"))), 0 if column == "work_type" else 1)
