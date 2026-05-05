import os
import sys
import unittest
from datetime import date
from pathlib import Path


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.app_services import AppServices
from stores.app_store import AppStore, AppState


class _FakeDB:
    def __init__(self):
        self.settings = {
            "ai_use_secondary": "1",
            "ai_api_key": "p_key",
            "ai_base_url": "p_url",
            "ai_model": "p_model",
            "ai2_api_key": "",
            "ai2_base_url": "s_url",
            "ai2_model": "s_model",
        }
        self.quick_logs = {
            "2026-04-08": [{"id": 1, "date": "2026-04-08", "time": "09:00", "end_time": "", "description": "A"}],
            "2026-04-09": [{"id": 2, "date": "2026-04-09", "time": "10:00", "end_time": "", "description": "B"}],
        }

    def get_setting(self, key, default=None, *, user_id=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value, *, user_id=None):
        self.settings[key] = str(value)

    def get_quick_logs_for_date(self, date_str, *, user_id=None):
        return list(self.quick_logs.get(date_str, []))

    def get_quick_logs_for_range(self, start_d, end_d, *, user_id=None):
        result = []
        for d, rows in self.quick_logs.items():
            if start_d <= d <= end_d:
                result.extend(rows)
        return result

    def month(self, ym, *, user_id=None):
        return []


class ArchitectureDecouplingTests(unittest.TestCase):
    def test_store_patch_and_subscribe(self):
        store = AppStore(AppState(lang="en_US", theme="blue"))
        snapshots = []
        store.subscribe(lambda s: snapshots.append((s.lang, s.theme)))
        store.patch(lang="zh_CN", theme="green")
        self.assertEqual(store.state.lang, "zh_CN")
        self.assertEqual(store.state.theme, "green")
        self.assertEqual(snapshots[-1], ("zh_CN", "green"))

    def test_services_quick_logs_for_weekly(self):
        services = AppServices(db=_FakeDB(), current_user_id=1)
        logs = services.quick_logs_for_type(
            selected=date(2026, 4, 9),
            current=date(2026, 4, 1),
            type_key="weekly",
        )
        self.assertEqual({item["id"] for item in logs}, {1, 2})

    def test_services_ai_params_secondary_fallback(self):
        services = AppServices(db=_FakeDB(), current_user_id=1)
        key, url, model = services.resolve_ai_params(secondary=True)
        self.assertEqual(key, "p_key")
        self.assertEqual(url, "s_url")
        self.assertEqual(model, "s_model")

    def test_ai_ui_delegates_prompt_and_worker_logic_to_services(self):
        ui_dir = Path(PROJECT_ROOT) / "worklogger" / "ui" / "dialogs"
        offenders: list[str] = []
        forbidden = (
            "AIWorker",
            "LocalModelWorker",
            "AiContextService",
            "system_prompt_for",
        )
        for path in ui_dir.glob("ai*.py"):
            text = path.read_text(encoding="utf-8")
            for needle in forbidden:
                if needle in text:
                    offenders.append(f"{path.name}:{needle}")

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

