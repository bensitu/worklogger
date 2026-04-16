from __future__ import annotations
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from calendar import monthrange
from typing import Callable, Iterable
import urllib.request
import json as _json
from PySide6.QtCore import QObject, Signal

from config.constants import APP_VERSION, GITHUB_RELEASES_API
from data.db import DB
from services.export_service import export_csv, import_csv, build_ics
from services.calendar_service import parse_ics_rich
from services import report_service
from services.key_store import get_secret, set_secret
from stores.app_store import AppState


class _UpdateBridge(QObject):
    done = Signal(str)


class AppServices:
    """Aggregate service layer.

    All business operations pass through here so the UI never touches
    ``DB`` directly. Heavy-lifting (report gen, CSV/ICS, AI calls) is
    delegated to specialised service modules.
    """

    def __init__(self, db: DB | None = None):
        self.db = db or DB()
        self._update_bridges: list[_UpdateBridge] = []

    def get_setting(self, key: str, default=None):
        return self.db.get_setting(key, default)

    def set_setting(self, key: str, value) -> None:
        self.db.set_setting(key, value)

    def get_record(self, day: str):
        return self.db.get(day)

    def save_record(self, day, start, end, break_hours, note, work_type="normal", overnight: int | None = None) -> None:
        self.db.save(day, start, end, break_hours, note, work_type, overnight=overnight)

    def month_records(self, ym: str):
        return self.db.month(ym)

    def all_records(self):
        return self.db.all_records()

    def add_quick_log(self, date_str: str, time_str: str, desc: str, end_time: str = "") -> int:
        return self.db.add_quick_log(date_str, time_str, desc, end_time)

    def update_quick_log(self, log_id: int, description: str, time_str: str = "", end_time: str = "") -> None:
        self.db.update_quick_log(log_id, description, time_str, end_time)

    def delete_quick_log(self, log_id: int) -> None:
        self.db.delete_quick_log(log_id)

    def quick_logs_for_date(self, date_str: str) -> list[dict]:
        return self.db.get_quick_logs_for_date(date_str)

    def quick_logs_for_range(self, start_d: str, end_d: str) -> list[dict]:
        return self.db.get_quick_logs_for_range(start_d, end_d)

    def quick_logs_for_type(self, selected: date, current: date, type_key: str) -> list[dict]:
        if type_key == "weekly":
            monday = selected - timedelta(days=selected.weekday())
            sunday = monday + timedelta(days=6)
            return self.quick_logs_for_range(monday.isoformat(), sunday.isoformat())
        if type_key == "monthly":
            y, m = current.year, current.month
            _, last = monthrange(y, m)
            return self.quick_logs_for_range(
                f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}",
            )
        return self.quick_logs_for_date(selected.isoformat())

    def get_calendar_events_for_date(self, day: str) -> list[dict]:
        return self.db.get_calendar_events_for_date(day)

    def get_calendar_events_for_range(self, start_d: str, end_d: str) -> list[dict]:
        return self.db.get_calendar_events_for_range(start_d, end_d)

    def clear_calendar_events(self) -> None:
        self.db.clear_calendar_events()

    def save_calendar_events(self, events: list, source_file: str = "") -> int:
        return self.db.save_calendar_events(events, source_file)

    def parse_calendar_file(self, path: str) -> list[dict]:
        return parse_ics_rich(path)

    def import_csv_file(self, path: str, required_cols: set, default_break: float = 1.0) -> tuple[int, list[str]]:
        return import_csv(path, self.db, required_cols, default_break=default_break)

    def export_csv_file(self, path: str, rows: Iterable) -> None:
        export_csv(path, list(rows))

    def export_month_ics(self, ym: str) -> str:
        rows = self.month_records(ym)
        return build_ics(rows)

    def generate_weekly_report(self, selected: date, work_hours: float, lang: str) -> str:
        return report_service.generate_weekly(selected, self.db, work_hours, lang)

    def generate_monthly_report(self, year: int, month: int, work_hours: float, lang: str) -> str:
        return report_service.generate_monthly(year, month, self.db, work_hours, lang)

    def check_update_async(
        self,
        t: dict,
        on_result: Callable[[str], None],
    ) -> None:
        """Check for a newer release in a background thread."""
        bridge = _UpdateBridge()
        self._update_bridges.append(bridge)

        def _deliver(msg: str) -> None:
            try:
                on_result(msg)
            finally:
                try:
                    self._update_bridges.remove(bridge)
                except ValueError:
                    pass

        bridge.done.connect(_deliver)

        def _fetch():
            msg = self._check_update_sync(t)
            bridge.done.emit(msg)

        threading.Thread(target=_fetch, daemon=True).start()

    def _check_update_sync(self, t: dict) -> str:
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"User-Agent": "WorkLogger/" + APP_VERSION},
        )
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                data = _json.loads(r.read())
            latest = data.get("tag_name", "").lstrip("v")
            if latest and latest != APP_VERSION:
                avail_tpl = t.get("about_update_available", "v{0} available!")
                try:
                    return avail_tpl.format(latest)
                except Exception:
                    return f"v{latest} available!"
            return t.get("about_up_to_date", "Already up to date")
        except Exception as exc:
            err = str(exc)[:120]
            template = t.get("about_update_error", "Update check failed: {0}")
            try:
                return template.format(err)
            except Exception:
                return f"Update check failed: {err}"

    def load_settings(self) -> AppState:
        return AppState(
            lang=self.get_setting("lang", "en"),
            theme=self.get_setting("theme", "blue"),
            dark=self.get_setting("dark", "0") == "1",
            work_hours=float(self.get_setting("work_hours", "8.0")),
            default_break=float(self.get_setting("default_break", "1.0")),
            monthly_target=float(self.get_setting("monthly_target", "168.0")),
            show_holidays=self.get_setting("show_holidays", "1") == "1",
            show_note_markers=self.get_setting("show_note_markers", "1") == "1",
            show_overnight_indicator=self.get_setting("show_overnight_indicator", "1") == "1",
            week_start_monday=self.get_setting("week_start_monday", "0") == "1",
            time_input_mode=self.get_setting("time_input_mode", "manual"),
        )

    def save_settings(self, state: AppState) -> None:
        mapping: dict[str, str] = {
            "lang": state.lang,
            "theme": state.theme,
            "dark": "1" if state.dark else "0",
            "work_hours": str(state.work_hours),
            "default_break": str(state.default_break),
            "monthly_target": str(state.monthly_target),
            "show_holidays": "1" if state.show_holidays else "0",
            "show_note_markers": "1" if state.show_note_markers else "0",
            "show_overnight_indicator": "1" if state.show_overnight_indicator else "0",
            "week_start_monday": "1" if state.week_start_monday else "0",
            "time_input_mode": state.time_input_mode,
        }
        for key, value in mapping.items():
            self.db.set_setting(key, value)

    def load_settings_snapshot(self) -> AppState:
        return self.load_settings()

    # ── Secret (API key) helpers ─────────────────────────────────────────
    # API keys are sensitive credentials.  These methods route through
    # key_store which tries the OS keychain first, then Fernet-encrypted DB.

    _SECRET_KEYS = {"ai_api_key", "ai2_api_key"}

    def get_secret(self, name: str) -> str:
        """Return secret *name*, decrypting if stored via key_store."""
        return get_secret(self.db, name)

    def set_secret(self, name: str, value: str) -> None:
        """Store secret *name* as securely as the environment allows."""
        set_secret(self.db, name, value)

    def resolve_ai_params(self, secondary: bool = False) -> tuple:
        from services.local_model_service import should_use_local_model
        from services.local_model_service import LOCAL_MODEL_SENTINEL
        if should_use_local_model(self):
            return LOCAL_MODEL_SENTINEL, "", ""
        if secondary and self.get_setting("ai_use_secondary", "0") == "1":
            key = self.get_secret("ai2_api_key") or self.get_secret("ai_api_key")
            url = self.get_setting("ai2_base_url", "") or self.get_setting("ai_base_url", "")
            mdl = self.get_setting("ai2_model", "") or self.get_setting("ai_model", "")
        else:
            key = self.get_secret("ai_api_key")
            url = self.get_setting("ai_base_url", "")
            mdl = self.get_setting("ai_model", "")
        return key, url, mdl
