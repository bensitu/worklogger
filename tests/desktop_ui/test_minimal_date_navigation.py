import os
import sys
import tempfile
import time
import unittest
from datetime import date
from types import SimpleNamespace


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from data.db import DB
from services.app_services import AppServices
from ui.main_window import App


class _FakeButton:
    def __init__(self):
        self.enabled = None
        self.down = None

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)

    def setDown(self, down):
        self.down = bool(down)


class MinimalDateNavigationTests(unittest.TestCase):
    def _services(self) -> AppServices:
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        db = DB(path)
        self.addCleanup(db.conn.close)
        services = AppServices(db=db)
        user_id = services.auth.register("alice", "secret123")
        services.set_current_user(user_id)
        return services

    def test_data_date_range_uses_current_user_records(self):
        services = self._services()
        other_id = services.auth.register("bob", "secret123")
        services.save_record("2026-04-20", "09:00", "18:00", 1.0, "")
        services.save_record("2026-04-22", "09:00", "18:00", 1.0, "")
        services.db.save(
            "2025-01-01",
            "09:00",
            "18:00",
            1.0,
            "",
            user_id=other_id,
        )

        self.assertEqual(
            services.get_data_date_range(),
            (date(2026, 4, 20), date(2026, 4, 22)),
        )

    def test_minimal_navigation_buttons_allow_blank_dates(self):
        app = App.__new__(App)
        app.store = SimpleNamespace(state=SimpleNamespace(minimal_mode=True))
        app._minimal_prev_day_btn = _FakeButton()
        app._minimal_next_day_btn = _FakeButton()

        app.selected = date(2026, 4, 20)
        App._update_minimal_date_nav(app)
        self.assertTrue(app._minimal_prev_day_btn.enabled)
        self.assertTrue(app._minimal_next_day_btn.enabled)

    def test_minimal_navigation_buttons_disable_only_at_date_limits(self):
        app = App.__new__(App)
        app.store = SimpleNamespace(state=SimpleNamespace(minimal_mode=True))
        app._minimal_prev_day_btn = _FakeButton()
        app._minimal_next_day_btn = _FakeButton()

        app.selected = date.min
        App._update_minimal_date_nav(app)
        self.assertFalse(app._minimal_prev_day_btn.enabled)
        self.assertTrue(app._minimal_next_day_btn.enabled)

        app.selected = date.max
        App._update_minimal_date_nav(app)
        self.assertTrue(app._minimal_prev_day_btn.enabled)
        self.assertFalse(app._minimal_next_day_btn.enabled)

    def test_minimal_navigation_shifts_across_blank_dates(self):
        selected_dates = []
        app = App.__new__(App)
        app.store = SimpleNamespace(state=SimpleNamespace(minimal_mode=True))
        app._minimal_prev_day_btn = _FakeButton()
        app._minimal_next_day_btn = _FakeButton()
        app._update_minimal_date_nav = lambda: None
        app._flash_date_nav_button = lambda _button: None
        app.select = selected_dates.append

        app.selected = date(2026, 4, 22)
        App._shift_minimal_day(app, -1)

        self.assertEqual(app.current, date(2026, 4, 1))
        self.assertEqual(selected_dates, [date(2026, 4, 21)])

    def test_data_date_range_query_stays_under_ui_budget(self):
        services = self._services()
        for day in range(1, 29):
            services.save_record(
                f"2026-04-{day:02d}",
                "09:00",
                "18:00",
                1.0,
                "",
            )

        start = time.perf_counter()
        services.get_data_date_range()
        elapsed = time.perf_counter() - start

        self.assertLess(elapsed, 0.3)


if __name__ == "__main__":
    unittest.main()

