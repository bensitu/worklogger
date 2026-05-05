import os
import sys
import tempfile
import unittest
from datetime import date
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from data.db import DB
from services.ai_context_service import AiContextService
from services.app_services import AppServices


class MultiUserIsolationTests(unittest.TestCase):
    def _services(self) -> AppServices:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        db = DB(path)
        self.addCleanup(db.conn.close)
        return AppServices(db=db)

    def test_records_settings_and_quick_logs_are_user_scoped(self):
        services = self._services()
        alice = services.auth.register("alice", "secret123")
        bob = services.auth.register("bob", "secret456")

        services.set_current_user(alice)
        services.save_record("2026-04-25", "09:00", "18:00", 1.0, "alice", "normal")
        services.set_setting("theme", "green")
        alice_log = services.add_quick_log("2026-04-25", "10:00", "alice note")

        services.set_current_user(bob)
        services.save_record("2026-04-25", "08:00", "17:00", 1.0, "bob", "normal")
        services.set_setting("theme", "blue")
        bob_log = services.add_quick_log("2026-04-25", "11:00", "bob note")

        self.assertEqual(services.get_record("2026-04-25").note, "bob")
        self.assertEqual(services.get_setting("theme"), "blue")
        self.assertEqual(
            [item["id"] for item in services.quick_logs_for_date("2026-04-25")],
            [bob_log],
        )

        services.set_current_user(alice)
        self.assertEqual(services.get_record("2026-04-25").note, "alice")
        self.assertEqual(services.get_setting("theme"), "green")
        self.assertEqual(
            [item["id"] for item in services.quick_logs_for_date("2026-04-25")],
            [alice_log],
        )

    def test_active_local_model_setting_is_user_scoped(self):
        services = self._services()
        alice = services.auth.register("alice", "secret123")
        bob = services.auth.register("bob", "secret456")
        catalog = [
            {"id": "qwen3_4b_instruct_2507_q4"},
            {"id": "qwen3_8b_q4"},
        ]
        manifest = [
            {"id": "qwen3_4b_instruct_2507_q4"},
            {"id": "qwen3_8b_q4"},
        ]

        with patch("services.local_model_service.load_catalog", return_value=catalog), \
             patch("services.local_model_service.load_manifest", return_value=manifest), \
             patch("services.local_model_service.get_default_model_id", return_value="qwen3_4b_instruct_2507_q4"):
            services.set_current_user(alice)
            services.set_active_local_model_id("qwen3_4b_instruct_2507_q4")
            services.set_current_user(bob)
            services.set_active_local_model_id("qwen3_8b_q4")

            self.assertEqual(services.get_active_local_model_id(), "qwen3_8b_q4")
            services.set_current_user(alice)
            self.assertEqual(
                services.get_active_local_model_id(),
                "qwen3_4b_instruct_2507_q4",
            )
            self.assertEqual(
                services.list_user_ids_using_model("qwen3_4b_instruct_2507_q4"),
                [alice],
            )

    def test_reports_only_include_current_user(self):
        services = self._services()
        alice = services.auth.register("alice", "secret123")
        bob = services.auth.register("bob", "secret456")

        services.set_current_user(alice)
        services.save_record("2026-04-25", "09:00", "18:00", 1.0, "alice report", "normal")
        services.set_current_user(bob)
        services.save_record("2026-04-25", "09:00", "18:00", 1.0, "bob report", "normal")

        report = services.generate_weekly_report(date(2026, 4, 25), 8.0, "en_US")
        self.assertIn("bob report", report)
        self.assertNotIn("alice report", report)

    def test_ai_context_only_includes_selected_period(self):
        services = self._services()
        user_id = services.auth.register("alice", "secret123")
        services.set_current_user(user_id)
        services.save_record("2026-05-04", "09:00", "18:00", 1.0, "inside", "normal")
        services.save_record("2026-05-11", "09:00", "18:00", 1.0, "outside", "normal")
        services.add_quick_log("2026-05-04", "10:00", "inside quick")
        services.add_quick_log("2026-05-11", "10:00", "outside quick")

        context = AiContextService(services).build_weekly_context(date(2026, 5, 4))

        self.assertIn("inside", context)
        self.assertIn("inside quick", context)
        self.assertNotIn("outside", context)
        self.assertNotIn("outside quick", context)

    def test_ai_context_respects_privacy_flags(self):
        services = self._services()
        user_id = services.auth.register("alice", "secret123")
        services.set_current_user(user_id)
        services.save_record("2026-05-04", "09:00", "18:00", 1.0, "private note", "normal")
        services.add_quick_log("2026-05-04", "10:00", "quick detail")
        services.save_calendar_events(
            [
                {
                    "date": "2026-05-04",
                    "start": "14:00",
                    "end": "15:00",
                    "summary": "Secret meeting",
                }
            ],
        )

        context = AiContextService(services).build_daily_context(
            date(2026, 5, 4),
            include_notes=False,
            include_calendar=True,
            include_calendar_titles=False,
            include_quick_log_details=False,
        )

        self.assertNotIn("private note", context)
        self.assertNotIn("quick detail", context)
        self.assertNotIn("Secret meeting", context)
        self.assertIn("Title hidden", context)
        self.assertIn("quick log entries excluded", context)


if __name__ == "__main__":
    unittest.main()

