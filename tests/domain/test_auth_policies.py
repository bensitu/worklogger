from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from worklogger.config.constants import REMEMBER_TOKEN_HASH_PREFIX
from worklogger.domain.auth.policies import (
    generate_recovery_key,
    lockout_seconds_for_failure_count,
    normalize_username,
    password_change_due,
    remember_token_expires_at,
    remember_token_is_expired,
    remember_token_storage_value,
    require_password,
)


class AuthPolicyTests(unittest.TestCase):
    def test_username_and_password_policy(self) -> None:
        self.assertEqual(normalize_username("  alice  "), "alice")
        with self.assertRaises(ValueError):
            normalize_username(" ")
        with self.assertRaises(ValueError):
            require_password("short")
        self.assertEqual(require_password("secret123"), "secret123")

    def test_recovery_key_is_grouped_hex_material(self) -> None:
        key = generate_recovery_key(token_bytes=4, group_size=2)
        self.assertRegex(key, r"^[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}-[0-9a-f]{2}$")

    def test_remember_token_policy_hashes_and_expires(self) -> None:
        stored = remember_token_storage_value("token-value")
        self.assertTrue(stored.startswith(REMEMBER_TOKEN_HASH_PREFIX))
        self.assertNotIn("token-value", stored)

        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        expires_at = remember_token_expires_at(now=now, lifetime_days=30)
        self.assertFalse(remember_token_is_expired(expires_at, now=now))
        self.assertTrue(
            remember_token_is_expired(
                expires_at,
                now=now + timedelta(days=31),
            )
        )

    def test_lockout_schedule_escalates_by_failure_count(self) -> None:
        schedule = ((5, 30), (10, 300), (15, 1800))
        self.assertIsNone(lockout_seconds_for_failure_count(4, lockout_schedule=schedule))
        self.assertEqual(lockout_seconds_for_failure_count(5, lockout_schedule=schedule), 30)
        self.assertEqual(lockout_seconds_for_failure_count(12, lockout_schedule=schedule), 300)
        self.assertEqual(lockout_seconds_for_failure_count(20, lockout_schedule=schedule), 1800)

    def test_password_change_due_uses_utc_age(self) -> None:
        now = datetime(2026, 5, 13, tzinfo=timezone.utc)
        self.assertTrue(password_change_due(None, now=now))
        self.assertFalse(password_change_due(now - timedelta(days=30), now=now))
        self.assertTrue(password_change_due(now - timedelta(days=91), now=now))


if __name__ == "__main__":
    unittest.main()
