import os
import sys
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from ui.main_window import App


class _FakeServices:
    def __init__(self, mapping):
        self._mapping = dict(mapping)

    def get_setting(self, key, default=None):
        return self._mapping.get(key, default)


class _DummyApp:
    def __init__(self, mapping):
        self.services = _FakeServices(mapping)


class _FakeStore:
    def __init__(self):
        self.last_patch = None
        self.state = type("State", (), {"work_hours": 8.0})()

    def patch(self, **kwargs):
        self.last_patch = kwargs
        if "work_hours" in kwargs:
            self.state.work_hours = kwargs["work_hours"]


class _DummyAppWithStore:
    def __init__(self):
        self.store = _FakeStore()

    @property
    def _state(self):
        return self.store.state


class SafeFloatSettingTests(unittest.TestCase):
    def test_returns_float_when_setting_exists(self):
        app = _DummyApp({"work_hours": "7.5"})
        value = App._safe_float_setting(app, "work_hours", 8.0)
        self.assertEqual(value, 7.5)

    def test_returns_default_when_setting_missing(self):
        app = _DummyApp({})
        value = App._safe_float_setting(app, "default_break", 1.0)
        self.assertEqual(value, 1.0)

    def test_returns_default_when_setting_invalid(self):
        app = _DummyApp({"monthly_target": "not-a-number"})
        value = App._safe_float_setting(app, "monthly_target", 168.0)
        self.assertEqual(value, 168.0)

    def test_work_hours_setter_uses_store_patch_without_name_error(self):
        app = _DummyAppWithStore()
        App.work_hours.fset(app, 9.5)
        self.assertEqual(app.store.last_patch, {"work_hours": 9.5})
        self.assertEqual(app.store.state.work_hours, 9.5)

    def test_work_hours_getter_reads_state(self):
        app = _DummyAppWithStore()
        app.store.state.work_hours = 7.0
        self.assertEqual(App.work_hours.fget(app), 7.0)


if __name__ == "__main__":
    unittest.main()

