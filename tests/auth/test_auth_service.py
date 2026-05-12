import os
import base64
import json
import sqlite3
import sys
import tempfile
import unittest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from config.constants import (
    FORCE_PASSWORD_CHANGE_SETTING_KEY,
    REMEMBER_TOKEN_HASH_PREFIX,
)
from data.db import DB, _DUMMY_PASSWORD_HASH, _DUMMY_PASSWORD_SALT
from services.app_services import AppServices
from services.oauth_service import OAuthError, OAuthService
from utils.formatters import format_timestamp_for_display


def _unsigned_test_jwt(claims: dict) -> str:
    header = {"alg": "RS256", "typ": "JWT"}

    def _enc(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{_enc(header)}.{_enc(claims)}."


class AuthServiceTests(unittest.TestCase):
    def _db(self) -> DB:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        db = DB(path)
        self.addCleanup(db.conn.close)
        return db

    def test_register_login_and_change_password(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123", "oldkey1234567890")
        self.assertFalse(services.db.get_user(user_id)["is_used"])
        self.assertEqual(services.auth.login("alice", "secret123"), user_id)
        self.assertFalse(services.db.get_user(user_id)["is_used"])
        services.set_current_user(user_id)
        services.mark_current_user_used()
        self.assertTrue(services.db.get_user(user_id)["is_used"])
        self.assertIsNone(services.db.verify_user("alice", "wrong"))

        new_recovery_key = services.auth.change_password(
            user_id,
            "secret123",
            "secret456",
        )
        self.assertTrue(new_recovery_key)
        self.assertIsNone(services.db.verify_user("alice", "secret123"))
        self.assertEqual(services.auth.login("alice", "secret456"), user_id)
        self.assertIsNone(
            services.db.verify_recovery_key("alice", "oldkey1234567890")
        )
        self.assertEqual(
            services.db.verify_recovery_key("alice", new_recovery_key),
            user_id,
        )

    def test_remember_token_login(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")
        saved = []
        def _capture_token(username, token):
            saved.append((username, token))

        with patch("services.app_services.save_remember_token", _capture_token):
            self.assertEqual(
                services.auth.login("alice", "secret123", remember=True),
                user_id,
            )
        self.assertTrue(saved)
        self.assertEqual(saved[0][0], "alice")
        stored = services.db.conn.execute(
            "SELECT remember_token FROM users WHERE id=?",
            (user_id,),
        ).fetchone()[0]
        self.assertNotEqual(stored, saved[0][1])
        self.assertTrue(stored.startswith(REMEMBER_TOKEN_HASH_PREFIX))
        self.assertEqual(services.auth.login_with_token(saved[0][1]), user_id)
        self.assertFalse(services.db.get_user(user_id)["is_used"])
        services.set_current_user(user_id)
        services.mark_current_user_used()
        self.assertTrue(services.db.get_user(user_id)["is_used"])

    def test_plaintext_remember_token_is_migrated_on_db_open(self):
        db = self._db()
        user_id = db.create_user("alice", "secret123")
        db.conn.execute(
            "UPDATE users SET remember_token=?, remember_token_expires_at=? "
            "WHERE id=?",
            ("legacy-token", "2999-01-01T00:00:00+00:00", user_id),
        )
        db.conn.commit()
        path = db.path
        db.conn.close()

        reopened = DB(path)
        self.addCleanup(reopened.conn.close)

        stored = reopened.conn.execute(
            "SELECT remember_token FROM users WHERE id=?",
            (user_id,),
        ).fetchone()[0]
        self.assertTrue(stored.startswith(REMEMBER_TOKEN_HASH_PREFIX))
        self.assertNotEqual(stored, "legacy-token")
        self.assertEqual(reopened.get_user_by_token("legacy-token")["id"], user_id)

    def test_legacy_pbkdf2_password_login_upgrades_hash(self):
        db = self._db()
        services = AppServices(db=db)
        salt = "00" * 16
        legacy_hash = DB._password_hash_with_iterations("secret123", salt, 100_000)
        db.conn.execute(
            "INSERT INTO users(username,password_hash,salt,is_admin) "
            "VALUES(?,?,?,0)",
            ("alice", legacy_hash, salt),
        )
        db.conn.commit()

        user_id = services.auth.login("alice", "secret123")

        row = db.conn.execute(
            "SELECT password_hash,salt FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertNotEqual(row[0], legacy_hash)
        self.assertEqual(row[0], DB._password_hash("secret123", row[1]))

    def test_legacy_pbkdf2_recovery_key_still_resets_password(self):
        db = self._db()
        services = AppServices(db=db)
        user_id = services.auth.register("alice", "secret123", "oldkey1234567890")
        salt = "11" * 16
        legacy_hash = DB._password_hash_with_iterations(
            "oldkey1234567890",
            salt,
            100_000,
        )
        db.conn.execute(
            "UPDATE users SET recovery_key_hash=?, recovery_salt=? WHERE id=?",
            (legacy_hash, salt, user_id),
        )
        db.conn.commit()

        new_recovery_key = services.auth.reset_password_with_recovery(
            "alice",
            "oldkey1234567890",
            "secret456",
        )
        self.assertTrue(new_recovery_key)
        self.assertEqual(services.auth.login("alice", "secret456"), user_id)
        row = db.conn.execute(
            "SELECT recovery_key_hash,recovery_salt FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
        self.assertNotEqual(row[0], legacy_hash)
        self.assertIsNone(db.verify_recovery_key("alice", "oldkey1234567890"))
        self.assertEqual(
            db.verify_recovery_key("alice", new_recovery_key),
            user_id,
        )

    def test_remember_token_expires(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")
        services.db.set_remember_token(user_id, "expired-token")
        services.db.conn.execute(
            "UPDATE users SET remember_token_expires_at=datetime('now', '-1 day') "
            "WHERE id=?",
            (user_id,),
        )
        services.db.conn.commit()

        self.assertIsNone(services.auth.login_with_token("expired-token"))
        self.assertIsNone(services.db.get_user_by_token("expired-token"))

    def test_remember_token_expiry_is_stored_as_utc(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")
        services.db.set_remember_token(user_id, "remember-token")

        row = services.db.conn.execute(
            "SELECT remember_token_expires_at FROM users WHERE id=?",
            (user_id,),
        ).fetchone()

        expires_at = datetime.fromisoformat(row[0])
        self.assertEqual(expires_at.tzinfo, timezone.utc)
        self.assertFalse(services.db._remember_token_is_expired(row[0]))

    def test_failed_logins_are_audit_logged_and_temporarily_locked(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")

        with patch("services.app_services.LOGIN_FAILURE_LOCK_THRESHOLD", 2), \
             patch("services.app_services.LOGIN_LOCKOUT_SECONDS", 30), \
             patch("services.app_services.LOGIN_LOCKOUT_SCHEDULE", ((2, 30),)), \
             self.assertLogs("services.app_services", level="WARNING") as logs:
            with self.assertRaises(ValueError):
                services.auth.login("alice", "wrong-pass")
            with self.assertRaises(ValueError):
                services.auth.login("alice", "wrong-pass")
            with self.assertRaises(ValueError):
                services.auth.login("alice", "secret123")

        log_text = "\n".join(logs.output)
        self.assertIn("Login failed for username=alice", log_text)
        self.assertIn("Login blocked for username=alice", log_text)

        services.db.conn.execute(
            "UPDATE login_attempts SET locked_until=? WHERE username=?",
            ("2000-01-01T00:00:00+00:00", "alice"),
        )
        services.db.conn.commit()

        self.assertEqual(services.auth.login("alice", "secret123"), user_id)
        self.assertIsNone(
            services.db.conn.execute(
                "SELECT 1 FROM login_attempts WHERE username=?",
                ("alice",),
            ).fetchone()
        )

    def test_login_lockout_schedule_preserves_failure_count_after_expiry(self):
        db = self._db()
        schedule = ((5, 30), (10, 300))

        locked_until = None
        for _ in range(5):
            failed_count, locked_until = db.record_login_failure(
                "alice",
                threshold=5,
                lockout_seconds=30,
                lockout_schedule=schedule,
            )

        self.assertEqual(failed_count, 5)
        self.assertIsNotNone(locked_until)
        db.conn.execute(
            "UPDATE login_attempts SET locked_until=? WHERE username=?",
            ("2000-01-01T00:00:00+00:00", "alice"),
        )
        db.conn.commit()

        self.assertIsNone(db.login_lockout_until("alice"))
        row = db.conn.execute(
            "SELECT failed_count, locked_until FROM login_attempts WHERE username=?",
            ("alice",),
        ).fetchone()
        self.assertEqual(row[0], 5)
        self.assertIsNone(row[1])

        for _ in range(5):
            failed_count, locked_until = db.record_login_failure(
                "alice",
                threshold=5,
                lockout_seconds=30,
                lockout_schedule=schedule,
            )

        self.assertEqual(failed_count, 10)
        self.assertIsNotNone(locked_until)
        self.assertGreater(
            (locked_until - datetime.now(timezone.utc)).total_seconds(),
            250,
        )

    def test_stale_login_attempts_are_pruned_on_db_open(self):
        db = self._db()
        old_at = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat(timespec="seconds")
        fresh_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        db.conn.execute(
            "INSERT INTO login_attempts"
            "(username,failed_count,locked_until,last_failed_at) VALUES(?,?,?,?)",
            ("old", 3, None, old_at),
        )
        db.conn.execute(
            "INSERT INTO login_attempts"
            "(username,failed_count,locked_until,last_failed_at) VALUES(?,?,?,?)",
            ("fresh", 1, None, fresh_at),
        )
        db.conn.commit()
        path = db.path
        db.conn.close()

        reopened = DB(path)
        self.addCleanup(reopened.conn.close)

        self.assertIsNone(
            reopened.conn.execute(
                "SELECT 1 FROM login_attempts WHERE username=?",
                ("old",),
            ).fetchone()
        )
        self.assertIsNotNone(
            reopened.conn.execute(
                "SELECT 1 FROM login_attempts WHERE username=?",
                ("fresh",),
            ).fetchone()
        )

    def test_format_timestamp_for_display_converts_from_utc(self):
        raw = "2026-04-28T00:00:00+00:00"
        expected = (
            datetime(2026, 4, 28, 0, 0, tzinfo=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )

        self.assertEqual(format_timestamp_for_display(raw), expected)

    def test_short_password_rejected(self):
        services = AppServices(db=self._db())
        with self.assertRaises(ValueError):
            services.auth.register("alice", "short7")

    def test_default_admin_session_forces_password_change(self):
        services = AppServices(db=self._db())

        services.ensure_default_user_session()

        self.assertEqual(services.current_username, "admin")
        self.assertEqual(
            services.db.get_setting(
                FORCE_PASSWORD_CHANGE_SETTING_KEY,
                user_id=services.current_user_id,
            ),
            "1",
        )

    def test_sql_identifier_validation_rejects_dynamic_sql_injection(self):
        db = self._db()
        with self.assertRaises(ValueError):
            db._columns("users; DROP TABLE users")
        with self.assertRaises(ValueError):
            db._row_count("users where 1=1")

    def test_admin_can_regenerate_recovery_key(self):
        services = AppServices(db=self._db())
        admin_id = services.auth.register("admin", "secret123", "originalkey123456")
        user_id = services.auth.register("alice", "secret123", "oldkey1234567890")
        services.set_current_user(admin_id)

        new_key = services.regenerate_recovery_key("alice")

        self.assertNotEqual(new_key, "oldkey1234567890")
        self.assertRegex(new_key, r"^[0-9a-f]{8}(-[0-9a-f]{8}){5}$")
        self.assertEqual(
            services.db.verify_recovery_key("alice", new_key),
            user_id,
        )
        self.assertIsNone(
            services.db.verify_recovery_key("alice", "oldkey1234567890")
        )
        user = services.db.get_user(user_id)
        self.assertTrue(user["recovery_key_created_at"])

    def test_recovery_password_reset_invalidates_old_key(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123", "oldkey1234567890")

        new_key = services.auth.reset_password_with_recovery(
            "alice",
            "oldkey1234567890",
            "secret456",
        )

        self.assertTrue(new_key)
        self.assertEqual(services.auth.login("alice", "secret456"), user_id)
        self.assertIsNone(
            services.db.verify_recovery_key("alice", "oldkey1234567890")
        )
        self.assertEqual(services.db.verify_recovery_key("alice", new_key), user_id)

    def test_missing_recovery_key_uses_dummy_hash_check(self):
        db = self._db()

        with patch.object(db, "_password_hash_matches", return_value=(False, False)) as hashed:
            self.assertIsNone(db.verify_recovery_key("missing", "badkey"))

        hashed.assert_called_once_with(
            "badkey",
            _DUMMY_PASSWORD_SALT,
            _DUMMY_PASSWORD_HASH,
        )

    def test_admin_password_reset_invalidates_old_key(self):
        services = AppServices(db=self._db())
        admin_id = services.auth.register("admin", "secret123", "adminkey12345678")
        user_id = services.auth.register("alice", "secret123", "oldkey1234567890")
        services.set_current_user(admin_id)

        new_key = services.admin_reset_password(
            "secret123",
            user_id,
            "secret456",
        )

        self.assertTrue(new_key)
        self.assertEqual(services.auth.login("alice", "secret456"), user_id)
        self.assertIsNone(
            services.db.verify_recovery_key("alice", "oldkey1234567890")
        )
        self.assertEqual(services.db.verify_recovery_key("alice", new_key), user_id)

    def test_admin_can_create_unused_user_with_forced_password_change(self):
        services = AppServices(db=self._db())
        admin_id = services.auth.register("admin", "secret123", "adminkey12345678")
        services.set_current_user(admin_id)

        user_id, initial_password = services.create_user_by_admin(
            "secret123",
            "alice",
            "initial123",
        )

        self.assertEqual(initial_password, "initial123")
        self.assertEqual(services.auth.login("alice", initial_password), user_id)
        self.assertEqual(
            services.db.get_setting(
                FORCE_PASSWORD_CHANGE_SETTING_KEY,
                user_id=user_id,
            ),
            "1",
        )
        user = services.db.get_user(user_id)
        self.assertFalse(user["is_used"])
        self.assertFalse(user["is_admin"])
        self.assertFalse(user["has_recovery_key"])

        new_recovery_key = services.auth.force_change_password(
            user_id,
            "changed123",
        )
        self.assertTrue(new_recovery_key)
        self.assertEqual(
            services.db.get_setting(
                FORCE_PASSWORD_CHANGE_SETTING_KEY,
                user_id=user_id,
            ),
            "0",
        )
        self.assertFalse(services.db.get_user(user_id)["is_used"])
        self.assertEqual(services.auth.login("alice", "changed123"), user_id)
        services.set_current_user(user_id)
        services.mark_current_user_used()
        self.assertTrue(services.db.get_user(user_id)["is_used"])
        self.assertEqual(
            services.db.verify_recovery_key("alice", new_recovery_key),
            user_id,
        )

    def test_admin_account_actions_are_audit_logged_without_secrets(self):
        services = AppServices(db=self._db())
        admin_id = services.auth.register("admin", "secret123", "adminkey12345678")
        services.set_current_user(admin_id)

        with self.assertLogs("services.app_services", level="INFO") as logs:
            user_id, _initial_password = services.create_user_by_admin(
                "secret123",
                "alice",
                "initial123",
            )
            recovery_key = services.admin_reset_password(
                "secret123",
                user_id,
                "secret456",
            )
            self.assertTrue(recovery_key)
            self.assertTrue(services.set_user_admin("secret123", user_id, True))

        log_text = "\n".join(logs.output)
        self.assertIn("Admin user creation", log_text)
        self.assertIn("Admin password reset", log_text)
        self.assertIn("Admin privilege change", log_text)
        self.assertIn("Admin=admin", log_text)
        self.assertIn("New User=alice", log_text)
        self.assertIn("Target User=alice", log_text)
        self.assertNotIn("secret123", log_text)
        self.assertNotIn("initial123", log_text)
        self.assertNotIn("secret456", log_text)
        self.assertNotIn(str(recovery_key), log_text)

    def test_admin_can_delete_non_admin_user_and_related_data(self):
        services = AppServices(db=self._db())
        admin_id = services.auth.register("admin", "secret123", "adminkey12345678")
        user_id = services.auth.register("alice", "secret123", "oldkey1234567890")
        services.db.save(
            "2026-04-25",
            "09:00",
            "18:00",
            1.0,
            "note",
            user_id=user_id,
        )
        services.db.set_setting("lang", "zh_CN", user_id=user_id)
        services.db.add_quick_log(
            "2026-04-25",
            "09:00",
            "task",
            user_id=user_id,
        )
        services.db.save_calendar_events(
            [{"date": "2026-04-25", "summary": "event"}],
            user_id=user_id,
        )
        services.db.save_report(
            "weekly",
            "2026-04-20",
            "2026-04-26",
            "report",
            user_id=user_id,
        )
        services.set_current_user(admin_id)

        with self.assertLogs("data.db", level="INFO") as logs:
            self.assertTrue(services.delete_user_by_admin("secret123", "alice"))

        self.assertIsNone(services.db.get_user_by_username("alice"))
        for table_name in ("worklog", "settings", "quick_logs", "calendar_events", "reports"):
            count = services.db.conn.execute(
                f"SELECT COUNT(*) FROM {table_name} WHERE user_id=?",
                (user_id,),
            ).fetchone()[0]
            self.assertEqual(count, 0, table_name)
        log_text = "\n".join(logs.output)
        self.assertIn("Deleted user account", log_text)
        self.assertIn("Administrator=admin", log_text)
        self.assertIn("Deleted Username=alice", log_text)
        self.assertIn("Deleted Related Records", log_text)
        self.assertIn("Work Log Records=1", log_text)
        self.assertIn("Settings=1", log_text)
        system_logs_table = services.db.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='system_logs'"
        ).fetchone()
        self.assertIsNone(system_logs_table)

    def test_delete_user_rejects_admin_and_bad_admin_password(self):
        services = AppServices(db=self._db())
        admin_id = services.auth.register("admin", "secret123", "adminkey12345678")
        services.auth.register("alice", "secret123", "oldkey1234567890")
        services.set_current_user(admin_id)

        with self.assertRaises(ValueError):
            services.delete_user_by_admin("wrongpass", "alice")
        with self.assertRaises(ValueError):
            services.delete_user_by_admin("secret123", "admin")

    def test_non_admin_cannot_regenerate_recovery_key(self):
        services = AppServices(db=self._db())
        services.auth.register("admin", "secret123", "adminkey12345678")
        user_id = services.auth.register("alice", "secret123", "oldkey1234567890")
        services.set_current_user(user_id)

        with self.assertRaises(PermissionError):
            services.regenerate_recovery_key("admin")

    def test_oauth_identity_lookup_uses_provider_and_subject(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")
        identity_id = services.db.create_oauth_identity(
            user_id,
            "google",
            "sub-1",
            "alice@example.com",
            "Alice",
        )

        found = services.db.get_oauth_identity("google", "sub-1")

        self.assertEqual(found["id"], identity_id)
        self.assertEqual(found["user_id"], user_id)
        self.assertIsNone(services.db.get_oauth_identity("microsoft", "sub-1"))

    def test_duplicate_provider_subject_is_rejected(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")
        services.db.create_oauth_identity(user_id, "google", "sub-1", None, None)

        with self.assertRaises(sqlite3.IntegrityError):
            services.db.create_oauth_identity(user_id, "google", "sub-1", None, None)

    def test_oauth_created_user_is_not_admin_and_tokens_are_not_stored(self):
        services = AppServices(db=self._db())

        user_id = services.auth.login_with_oauth_identity(
            "google",
            "sub-1",
            "alice@example.com",
            "Alice",
        )

        self.assertFalse(services.db.get_user(user_id)["is_admin"])
        identity = services.db.get_oauth_identity("google", "sub-1")
        self.assertEqual(identity["user_id"], user_id)
        columns = {
            row[1]
            for row in services.db.conn.execute("PRAGMA table_info(oauth_identities)")
        }
        self.assertNotIn("access_token", columns)
        self.assertNotIn("refresh_token", columns)
        self.assertNotIn("id_token", columns)

    def test_unlinking_identity_does_not_remove_user(self):
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")
        identity_id = services.auth.link_oauth_identity(
            user_id,
            "microsoft",
            "sub-1",
            "alice@example.com",
            "Alice",
        )

        services.auth.unlink_oauth_identity(user_id, identity_id)

        self.assertIsNotNone(services.db.get_user(user_id))
        self.assertEqual(services.db.list_oauth_identities(user_id), [])

    def test_oauth_pkce_challenge_generation(self):
        verifier = "abc123"
        expected = base64.urlsafe_b64encode(
            __import__("hashlib").sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        self.assertEqual(OAuthService.code_challenge(verifier), expected)

    def test_oauth_state_verification_rejects_mismatch(self):
        with self.assertRaises(OAuthError):
            OAuthService.verify_state(expected="expected", actual="actual")

    def test_oauth_id_token_validation_extracts_identity_claims(self):
        config = OAuthService.default_config("google", "client-id")
        token = _unsigned_test_jwt({
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "sub": "subject-1",
            "email": "alice@example.com",
            "name": "Alice",
            "nonce": "nonce",
            "exp": int(time.time()) + 3600,
        })

        expected_claims = {
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "sub": "subject-1",
            "email": "alice@example.com",
            "name": "Alice",
            "nonce": "nonce",
            "exp": int(time.time()) + 3600,
        }
        with patch(
            "services.oauth_service.validate_oidc_id_token",
            return_value=expected_claims,
        ) as validate:
            claims = OAuthService.validate_id_token(token, config=config, nonce="nonce")
        validate.assert_called_once_with(
            token,
            audience="client-id",
            issuer=("https://accounts.google.com", "accounts.google.com"),
            nonce="nonce",
            jwks_uri=config.jwks_uri,
            verify_signature=True,
        )
        identity = OAuthService.identity_from_claims("google", claims)

        self.assertEqual(identity.provider, "google")
        self.assertEqual(identity.subject, "subject-1")
        self.assertEqual(identity.email, "alice@example.com")
        self.assertEqual(identity.display_name, "Alice")

    def test_oauth_id_token_validation_requires_signature_configuration(self):
        config = OAuthService.default_config("google", "client-id")
        config = type(config)(
            provider=config.provider,
            client_id=config.client_id,
            authorization_endpoint=config.authorization_endpoint,
            token_endpoint=config.token_endpoint,
            issuer=config.issuer,
            jwks_uri="",
            scopes=config.scopes,
        )
        token = _unsigned_test_jwt({
            "iss": "https://accounts.google.com",
            "aud": "client-id",
            "sub": "subject-1",
            "nonce": "nonce",
            "exp": int(time.time()) + 3600,
        })

        with self.assertRaises(OAuthError):
            OAuthService.validate_id_token(token, config=config, nonce="nonce")


if __name__ == "__main__":
    unittest.main()
