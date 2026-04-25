from __future__ import annotations
import os
from pathlib import Path
import sys
import threading
import re
from dataclasses import dataclass
from datetime import date, timedelta
from calendar import monthrange
from typing import Callable, Iterable
import ssl
import urllib.request
import urllib.error
import json as _json
from PySide6.QtCore import QObject, Signal

from config.constants import (
    APP_VERSION,
    CUSTOM_THEME_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_SETTING_KEY,
    GITHUB_RELEASES_API,
    LANG_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    THEME_SETTING_KEY,
    TIME_INPUT_MODE_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
    WORK_HOURS_SETTING_KEY,
)
from config.themes import DEFAULT_CUSTOM_COLOR, set_custom_theme
from data.db import DB
from services.export_service import export_csv, import_csv, build_ics
from services.calendar_service import parse_ics_rich
from services import report_service
from services.key_store import get_secret, set_secret
from stores.app_store import AppState
from utils.i18n import _, detect_system_language


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

    def resolve_initial_language(self) -> str:
        saved = self.get_setting(LANG_SETTING_KEY)
        if saved:
            return str(saved)

        detected = detect_system_language()
        if detected is not None:
            self.set_setting(LANG_SETTING_KEY, detected)
            return detected
        return "en_US"

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
        translator: Callable[[str], str],
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
            msg = self._check_update_sync(translator)
            bridge.done.emit(msg)

        threading.Thread(target=_fetch, daemon=True).start()

    @staticmethod
    def _parse_semver(version: str) -> tuple[int, int, int] | None:
        """Parse a semantic version into (major, minor, patch)."""
        m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", (version or "").strip())
        if not m:
            return None
        major = int(m.group(1))
        minor = int(m.group(2) or 0)
        patch = int(m.group(3) or 0)
        return (major, minor, patch)

    @classmethod
    def _is_remote_newer(cls, latest: str, current: str) -> bool:
        """Return True only when remote semantic version is strictly newer."""
        latest_v = cls._parse_semver(latest)
        current_v = cls._parse_semver(current)
        if latest_v is None or current_v is None:
            return False
        return latest_v > current_v

    @staticmethod
    def _certifi_cafile_candidates() -> list[Path]:
        candidates: list[Path] = []
        try:
            import importlib
            certifi = importlib.import_module("certifi")
            where = getattr(certifi, "where", lambda: None)()
            if where:
                candidates.append(Path(where))
        except Exception:
            pass

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "certifi" / "cacert.pem")

        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "certifi" / "cacert.pem")
            candidates.append(exe_dir.parent / "Resources" / "certifi" / "cacert.pem")
        except Exception:
            pass

        deduped: list[Path] = []
        seen: set[str] = set()
        for path in candidates:
            key = os.path.normcase(str(path.resolve(strict=False)))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(path)
        return deduped

    @classmethod
    def _build_update_ssl_context(cls) -> ssl.SSLContext:
        for cafile in cls._certifi_cafile_candidates():
            try:
                if cafile.is_file():
                    return ssl.create_default_context(cafile=str(cafile))
            except Exception:
                continue
        return ssl.create_default_context()

    def _check_update_sync(self, translator: Callable[[str], str]) -> str:
        _tr = translator if callable(translator) else _
        req = urllib.request.Request(
            GITHUB_RELEASES_API,
            headers={"User-Agent": "WorkLogger/" + APP_VERSION},
        )
        context = self._build_update_ssl_context()
        try:
            with urllib.request.urlopen(req, timeout=8, context=context) as r:
                data = _json.loads(r.read())
            latest = data.get("tag_name", "").lstrip("vV").strip()
            if latest and self._is_remote_newer(latest, APP_VERSION):
                avail_tpl = _tr("New version available: v{0}")
                try:
                    return avail_tpl.format(latest)
                except Exception:
                    return avail_tpl
            return _tr("You are on the latest version")
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(reason):
                return _tr(
                    "Could not verify the update server certificate. "
                    "Please check your network trust settings and try again."
                )
            err = str(exc)[:120]
            template = _tr("Could not check for updates: {0}")
            try:
                return template.format(err)
            except Exception:
                return template
        except Exception as exc:
            err = str(exc)[:120]
            template = _tr("Could not check for updates: {0}")
            try:
                return template.format(err)
            except Exception:
                return template

    def load_settings(self) -> AppState:
        custom_color = set_custom_theme(
            self.get_setting(CUSTOM_THEME_SETTING_KEY, DEFAULT_CUSTOM_COLOR)
        )
        return AppState(
            lang=self.get_setting(LANG_SETTING_KEY, "en_US"),
            theme=self.get_setting(THEME_SETTING_KEY, "blue"),
            custom_color=custom_color,
            dark=self.get_setting(DARK_MODE_SETTING_KEY, "0") == "1",
            work_hours=float(self.get_setting(WORK_HOURS_SETTING_KEY, "8.0")),
            default_break=float(self.get_setting(DEFAULT_BREAK_SETTING_KEY, "1.0")),
            monthly_target=float(self.get_setting(MONTHLY_TARGET_SETTING_KEY, "168.0")),
            show_holidays=self.get_setting(SHOW_HOLIDAYS_SETTING_KEY, "1") == "1",
            show_note_markers=self.get_setting(SHOW_NOTE_MARKERS_SETTING_KEY, "1") == "1",
            show_overnight_indicator=self.get_setting(SHOW_OVERNIGHT_INDICATOR_SETTING_KEY, "1") == "1",
            week_start_monday=self.get_setting(WEEK_START_MONDAY_SETTING_KEY, "0") == "1",
            time_input_mode=self.get_setting(TIME_INPUT_MODE_SETTING_KEY, "manual"),
            minimal_mode=self.get_setting(MINIMAL_MODE_SETTING_KEY, "0") == "1",
        )

    def save_settings(self, state: AppState) -> None:
        mapping: dict[str, str] = {
            LANG_SETTING_KEY: state.lang,
            THEME_SETTING_KEY: state.theme,
            CUSTOM_THEME_SETTING_KEY: state.custom_color or DEFAULT_CUSTOM_COLOR,
            DARK_MODE_SETTING_KEY: "1" if state.dark else "0",
            WORK_HOURS_SETTING_KEY: str(state.work_hours),
            DEFAULT_BREAK_SETTING_KEY: str(state.default_break),
            MONTHLY_TARGET_SETTING_KEY: str(state.monthly_target),
            SHOW_HOLIDAYS_SETTING_KEY: "1" if state.show_holidays else "0",
            SHOW_NOTE_MARKERS_SETTING_KEY: "1" if state.show_note_markers else "0",
            SHOW_OVERNIGHT_INDICATOR_SETTING_KEY: "1" if state.show_overnight_indicator else "0",
            WEEK_START_MONDAY_SETTING_KEY: "1" if state.week_start_monday else "0",
            TIME_INPUT_MODE_SETTING_KEY: state.time_input_mode,
            MINIMAL_MODE_SETTING_KEY: "1" if state.minimal_mode else "0",
        }
        for key, value in mapping.items():
            self.db.set_setting(key, value)

    def set_custom_theme(self, accent_hex: str) -> AppState:
        normalized = set_custom_theme(accent_hex)
        self.db.set_setting(CUSTOM_THEME_SETTING_KEY, normalized)
        self.db.set_setting(THEME_SETTING_KEY, "custom")
        return self.load_settings()

    def toggle_minimal_mode(self, enabled: bool) -> AppState:
        self.db.set_setting(MINIMAL_MODE_SETTING_KEY, "1" if enabled else "0")
        return self.load_settings()

    def load_settings_snapshot(self) -> AppState:
        return self.load_settings()

    # Secret (API key) helpers.
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
