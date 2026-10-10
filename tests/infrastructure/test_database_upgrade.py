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
from worklogger.infrastructure.security.key_store import EncryptedSettingsKeyStore, FileMachineKeyProvider, HmacSecretBox, NoKeyringBackend
from worklogger.infrastructure.database.upgrade import upgrade_database
from worklogger.infrastructure.database.migrations import migration_008_account_preferences


class DatabaseUpgradeTests(unittest.TestCase):
    def test_unversioned_current_layout_preserves_periods_classifications_and_memos(self):
        from datetime import date
        from worklogger.domain.worklog.models import WorkLog
        from worklogger.app.use_cases.work_types import WorkTypeService
        from worklogger.infrastructure.repositories.work_type_sqlite import SQLiteWorkTypeRepository
        from worklogger.infrastructure.repositories.note_sqlite import SQLiteDailyNoteRepository
        with tempfile.TemporaryDirectory() as directory:
            factory = SQLiteConnectionFactory(Path(directory) / "current.db")
            MigrationRunner(factory).run_pending()
            auth = SQLiteAuthRepository(factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
            user = auth.create_user("sample", "example-password", recovery_key=None, is_admin=False)
            auth.set_display_name(user.id, "Mary", expected_display_name="")
            types = WorkTypeService(user.id, SQLiteWorkTypeRepository(factory))
            definition = types.save("Research", "work").value
            records = SQLiteWorkLogRepository(factory)
            day = date(2026, 5, 20)
            first = records.save_entry(WorkLog(user.id, day, "09:00", "10:00", note="Entry content", work_type=definition))
            edited = records.save_entry(replace(first, note="Revised content"))
            second = records.save_entry(WorkLog(user.id, day, "10:00", "11:00", note="Another period"))
            with factory.transaction() as connection:
                connection.execute("INSERT INTO daily_notes(user_id,d,content) VALUES(?,?,?)", (user.id, day.isoformat(), "Independent memo"))
                connection.execute("DROP TABLE schema_migrations")
            self.assertEqual(MigrationRunner(factory).run_pending(), tuple(range(1,11)))
            self.assertEqual(auth.get_by_id(user.id).display_name, "Mary")
            self.assertEqual(records.list_for_day(user.id, day), (edited, second))
            self.assertEqual(types.list_types().value, (definition,))
            self.assertEqual(SQLiteDailyNoteRepository(factory).get_for_day(user.id, day).content, "Independent memo")
            self.assertEqual(MigrationRunner(factory).run_pending(), ())

    def test_explicit_upgrade_keeps_source_and_publishes_only_complete_results(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"source.db", Path(directory)/"updated.db"
            self.create_source(source, SCHEMAS[1])
            original = source.read_bytes()
            with patch.object(migration_008_account_preferences, "up", side_effect=OSError("interrupted upgrade")):
                with self.assertRaises(OSError):
                    upgrade_database(source, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(source.read_bytes(), original)
            report = upgrade_database(source,destination)
            self.assertEqual((report.accounts,report.time_records,report.reports),(1,2,1))
            self.assertEqual(report.applied_versions,tuple(range(1,11)))
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
                store = EncryptedSettingsKeyStore(settings,user_id=17,keyring_backend=NoKeyringBackend(),secret_box=HmacSecretBox(key_provider))
                result = store.get_secret("ai_api_key")
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
                self.assertEqual(MigrationRunner(factory).run_pending(), tuple(range(1,11)))
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
