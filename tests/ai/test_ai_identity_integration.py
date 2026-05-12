import base64
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from datetime import date
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from data.db import DB
from services import analytics_service
from services.ai_chat_session import AiChatSession
from services.ai_context_service import AiContextService
from services.app_services import AppServices
from services.identity.brokers.firebase import FirebaseIdentityBroker
from services.identity.config import FirebaseBrokerConfig, provider_available, provider_configured
from services.identity.models import ExternalIdentity
from services.identity.pkce import build_code_challenge
from services.identity.token_validation import validate_oidc_id_token
from services.identity.errors import IdentityTokenInvalid


def _jwt(claims: dict, alg: str = "RS256") -> str:
    header = {"alg": alg, "typ": "JWT"}

    def enc(data: dict) -> str:
        raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{enc(header)}.{enc(claims)}."


class AIIdentityIntegrationTests(unittest.TestCase):
    def _db(self) -> DB:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        db = DB(path)
        self.addCleanup(db.conn.close)
        return db

    def _services(self) -> AppServices:
        services = AppServices(db=self._db())
        user_id = services.auth.register("alice", "secret123")
        services.set_current_user(user_id)
        return services

    def test_ai_chat_session_trims_and_resets(self):
        session = AiChatSession("system prompt", max_messages=5, token_budget=1000)
        for idx in range(5):
            session.add_user_message(f"user {idx}")
            session.add_assistant_message(f"assistant {idx}")

        messages = session.get_messages()

        self.assertEqual(messages[0]["role"], "system")
        self.assertLessEqual(len(messages), 5)
        self.assertEqual(messages[1]["role"], "user")
        self.assertEqual(session.last_assistant_message(), "assistant 4")
        session.reset()
        self.assertEqual(session.message_count(), 1)

    def test_ai_chat_session_thread_safe_append(self):
        session = AiChatSession("system prompt", max_messages=50)

        def add_pair(idx: int) -> None:
            session.add_user_message(f"user {idx}")
            session.add_assistant_message(f"assistant {idx}")

        threads = [threading.Thread(target=add_pair, args=(idx,)) for idx in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertGreaterEqual(session.message_count(), 3)
        self.assertEqual(session.get_messages()[0]["role"], "system")

    def test_ai_context_defaults_hide_notes_and_calendar_titles(self):
        services = self._services()
        services.save_record(
            "2026-05-01",
            "09:00",
            "18:00",
            1.0,
            "private note",
            "normal",
        )
        services.save_calendar_events([
            {
                "date": "2026-05-01",
                "summary": "Private meeting title",
                "start": None,
                "end": None,
            }
        ])
        services.add_quick_log("2026-05-01", "10:00", "Implement feature")

        context = AiContextService(services).build_daily_context(date(2026, 5, 1))

        self.assertNotIn("private note", context)
        self.assertNotIn("Private meeting title", context)
        self.assertIn("Title hidden", context)
        self.assertIn("Implement feature", context)

    def test_ai_analytics_context_serializes_leave_conditionally(self):
        services = self._services()
        bundle = analytics_service.ChartDataBundle(
            bar_data=[("Jan", 120.0)],
            line_data=[("Jan", 7.5)],
            leave_indices={0},
            leave_line_data=[8.0],
            leave_hours_data=[("Jan", 8.0)],
        )

        without_leave = AiContextService(services).build_analytics_context(
            year=2026,
            month=5,
            metric="Work hours",
            chart_mode="Bar",
            include_leave=False,
            monthly_bundle=bundle,
        )
        with_leave = AiContextService(services).build_analytics_context(
            year=2026,
            month=5,
            metric="Work hours",
            chart_mode="Bar",
            include_leave=True,
            monthly_bundle=bundle,
        )

        self.assertNotIn("Leave hours", without_leave)
        self.assertIn("Leave hours", with_leave)
        self.assertIn("120.00", with_leave)

    def test_external_identity_db_uses_broker_issuer_provider_subject(self):
        services = self._services()
        identity = ExternalIdentity(
            provider="google",
            broker="firebase",
            issuer="https://securetoken.google.com/worklogger-2026",
            subject="firebase-local-id",
            email="alice@example.com",
            display_name="Alice",
            federated_subject="google-sub",
            raw_provider="google.com",
        )
        identity_id = services.db.create_external_identity(services.current_user_id, identity)

        found = services.db.get_external_identity(
            "firebase",
            "https://securetoken.google.com/worklogger-2026",
            "google",
            "firebase-local-id",
        )

        self.assertEqual(found["id"], identity_id)
        self.assertEqual(found["federated_subject"], "google-sub")
        columns = {
            row[1]
            for row in services.db.conn.execute("PRAGMA table_info(external_identities)")
        }
        self.assertNotIn("refresh_token", columns)
        self.assertNotIn("id_token", columns)
        with self.assertRaises(sqlite3.IntegrityError):
            services.db.create_external_identity(services.current_user_id, identity)

    def test_auth_login_with_external_identity_creates_non_admin_user(self):
        services = AppServices(db=self._db())
        user_id = services.auth.login_with_external_identity(
            ExternalIdentity(
                provider="google",
                broker="firebase",
                issuer="firebase",
                subject="firebase-local-id",
                email="alice@example.com",
            )
        )

        self.assertFalse(services.db.get_user(user_id)["is_admin"])
        self.assertEqual(
            services.db.get_external_identity("firebase", "firebase", "google", "firebase-local-id")["user_id"],
            user_id,
        )

    def test_external_identity_login_clears_password_failures(self):
        services = self._services()
        identity = ExternalIdentity(
            provider="google",
            broker="firebase",
            issuer="firebase",
            subject="firebase-local-id",
            email="alice@example.com",
        )
        services.db.create_external_identity(services.current_user_id, identity)
        services.db.record_login_failure(
            "alice",
            threshold=1,
            lockout_seconds=30,
        )

        self.assertEqual(
            services.auth.login_with_external_identity(identity),
            services.current_user_id,
        )

        self.assertIsNone(
            services.db.conn.execute(
                "SELECT 1 FROM login_attempts WHERE username=?",
                ("alice",),
            ).fetchone()
        )

    def test_identity_provider_availability_requires_google_and_firebase_config(self):
        env = {
            "WORKLOGGER_IDENTITY_ENABLED": "1",
            "WORKLOGGER_GOOGLE_LOGIN_ENABLED": "1",
            "WORKLOGGER_GOOGLE_CLIENT_ID": "google-client",
            "WORKLOGGER_FIREBASE_API_KEY": "firebase-key",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(provider_configured("google"))
            self.assertTrue(provider_available("google"))
            self.assertFalse(provider_available("microsoft"))

    def test_firebase_broker_maps_local_id_as_subject(self):
        response = {
            "localId": "firebase-local-id",
            "email": "alice@example.com",
            "displayName": "Alice",
            "federatedId": "google-sub",
            "providerId": "google.com",
            "idToken": "firebase-id-token",
            "refreshToken": "firebase-refresh-token",
            "expiresIn": "3600",
        }
        with patch("services.identity.brokers.firebase.post_json", return_value=response):
            result = FirebaseIdentityBroker().sign_in_with_google_id_token(
                "google-id-token",
                config=FirebaseBrokerConfig(
                    api_key="firebase-key",
                    project_id="worklogger-2026",
                ),
            )

        self.assertEqual(result.identity.subject, "firebase-local-id")
        self.assertEqual(result.identity.federated_subject, "google-sub")
        self.assertEqual(result.refresh_token, "firebase-refresh-token")

    def test_pkce_and_token_validation_reject_alg_none(self):
        verifier = "abc123"
        expected = base64.urlsafe_b64encode(
            __import__("hashlib").sha256(verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        self.assertEqual(build_code_challenge(verifier), expected)
        token = _jwt(
            {
                "iss": "https://accounts.google.com",
                "aud": "client-id",
                "sub": "subject",
                "nonce": "nonce",
                "exp": int(time.time()) + 60,
            },
            alg="none",
        )
        with self.assertRaises(IdentityTokenInvalid):
            validate_oidc_id_token(
                token,
                audience="client-id",
                issuer="https://accounts.google.com",
                nonce="nonce",
                verify_signature=False,
            )


if __name__ == "__main__":
    unittest.main()
