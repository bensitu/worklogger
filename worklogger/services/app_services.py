from __future__ import annotations
import os
from pathlib import Path
import shutil
import sys
import threading
import re
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from calendar import monthrange
from typing import Callable, Iterable
import ssl
import sqlite3
import urllib.request
import urllib.error
import json as _json
from PySide6.QtCore import QObject, Signal

from config.constants import (
    APP_VERSION,
    BACKUP_REMINDER_DAYS,
    CUSTOM_THEME_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_SETTING_KEY,
    DEFAULT_ADMIN_USER,
    FORCE_PASSWORD_CHANGE_SETTING_KEY,
    GITHUB_RELEASES_API,
    LANG_SETTING_KEY,
    LAST_BACKUP_KEY,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_SETTING_KEY,
    PASSWORD_CHANGE_REMINDER_DAYS,
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
from services.session_store import (
    clear_active_remember_user,
    clear_remember_token,
    save_remember_token,
)
from stores.app_store import AppState
from utils.i18n import _, detect_system_language


class _UpdateBridge(QObject):
    done = Signal(str)


class AuthService:
    def __init__(self, db: DB):
        self.db = db

    @staticmethod
    def generate_recovery_key() -> str:
        return secrets.token_hex(16)

    def register(
        self,
        username: str,
        password: str,
        recovery_key: str | None = None,
    ) -> int:
        username = username.strip()
        if not username:
            raise ValueError("username_required")
        if len(password) < 6:
            raise ValueError("password_too_short")
        recovery_key = recovery_key.strip() if recovery_key else None
        is_first_user = self.db.user_count() == 0
        try:
            return self.db.create_user(
                username,
                password,
                recovery_key=recovery_key,
                is_admin=is_first_user,
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("username_exists") from exc

    def login(self, username: str, password: str, remember: bool = False) -> int:
        user_id = self.db.verify_user(username, password)
        if user_id is None:
            raise ValueError("invalid_credentials")
        if remember:
            token = secrets.token_urlsafe(32)
            self.db.set_remember_token(user_id, token)
            try:
                save_remember_token(username, token)
            except Exception:
                self.db.set_remember_token(user_id, None)
                raise
        else:
            self.db.set_remember_token(user_id, None)
            clear_remember_token(username)
            clear_active_remember_user()
        return user_id

    def login_with_token(self, token: str) -> int | None:
        user = self.db.get_user_by_token(token)
        return int(user["id"]) if user else None

    def reset_password_with_recovery(
        self,
        username: str,
        recovery_key: str,
        new_pw: str,
    ) -> bool:
        if len(new_pw) < 6:
            raise ValueError("password_too_short")
        user_id = self.db.verify_recovery_key(username, recovery_key)
        if user_id is None:
            return False
        changed = self.db.reset_password(user_id, new_pw)
        if changed:
            self.db.set_setting(
                FORCE_PASSWORD_CHANGE_SETTING_KEY,
                "0",
                user_id=user_id,
            )
            user = self.db.get_user(user_id)
            clear_remember_token(user["username"] if user else username)
        return changed

    def change_password(self, user_id: int, old_pw: str, new_pw: str) -> bool:
        if len(new_pw) < 6:
            raise ValueError("password_too_short")
        changed = self.db.change_password(user_id, old_pw, new_pw)
        if changed:
            self.db.set_setting(
                FORCE_PASSWORD_CHANGE_SETTING_KEY,
                "0",
                user_id=user_id,
            )
        return changed

    def change_password_for_username(
        self,
        username: str,
        old_pw: str,
        new_pw: str,
    ) -> bool:
        user_id = self.db.verify_user(username, old_pw)
        if user_id is None:
            return False
        return self.change_password(user_id, old_pw, new_pw)

    def logout(self, user_id: int | None = None) -> None:
        if user_id is not None:
            user = self.db.get_user(user_id)
            self.db.set_remember_token(user_id, None)
            clear_remember_token(user["username"] if user else None)
        else:
            clear_remember_token()

    def is_admin(self, user_id: int) -> bool:
        return self.db.is_admin(user_id)

    def list_users_for_admin(self, admin_user_id: int) -> list[dict]:
        if not self.db.is_admin(admin_user_id):
            raise PermissionError("admin_required")
        return self.db.list_users()

    def admin_reset_password(
        self,
        admin_user_id: int,
        admin_password: str,
        target_user_id: int,
        new_pw: str,
        *,
        clear_remember: bool = True,
    ) -> bool:
        if len(new_pw) < 6:
            raise ValueError("password_too_short")
        if not self.db.is_admin(admin_user_id):
            raise PermissionError("admin_required")
        if not self.db.verify_user_id(admin_user_id, admin_password):
            raise ValueError("admin_password_incorrect")
        target = self.db.get_user(target_user_id)
        if not target:
            return False
        changed = self.db.reset_password(target_user_id, new_pw)
        if changed:
            self.db.set_setting(
                FORCE_PASSWORD_CHANGE_SETTING_KEY,
                "1",
                user_id=target_user_id,
            )
            if clear_remember:
                clear_remember_token(target["username"])
        return changed

    def set_user_admin(
        self,
        admin_user_id: int,
        admin_password: str,
        target_user_id: int,
        enabled: bool,
    ) -> bool:
        if not self.db.is_admin(admin_user_id):
            raise PermissionError("admin_required")
        if not self.db.verify_user_id(admin_user_id, admin_password):
            raise ValueError("admin_password_incorrect")
        if not enabled and self.db.is_admin(target_user_id) and self.db.admin_count() <= 1:
            raise ValueError("last_admin")
        return self.db.set_admin(target_user_id, enabled)

    def regenerate_recovery_key(
        self,
        admin_user_id: int,
        target_username: str,
    ) -> str:
        if not self.db.is_admin(admin_user_id):
            raise PermissionError("admin_required")
        target_username = target_username.strip()
        if not target_username:
            raise ValueError("username_required")
        return self.db.regenerate_recovery_key(target_username)


class AppServices:
    """Aggregate service layer.

    All business operations pass through here so the UI never touches
    ``DB`` directly. Heavy-lifting (report gen, CSV/ICS, AI calls) is
    delegated to specialised service modules.
    """

    def __init__(self, db: DB | None = None, current_user_id: int | None = None):
        self.db = db or DB()
        self.auth = AuthService(self.db)
        self.current_user_id: int | None = current_user_id
        self.current_username: str | None = None
        if current_user_id is not None and hasattr(self.db, "get_user"):
            user = self.db.get_user(current_user_id)
            self.current_username = user["username"] if user else None
        self._update_bridges: list[_UpdateBridge] = []

    def set_current_user(self, user_id: int, username: str | None = None) -> None:
        self.current_user_id = int(user_id)
        if username is None:
            user = self.db.get_user(self.current_user_id)
            username = user["username"] if user else None
        self.current_username = username

    def clear_current_user(self) -> None:
        self.current_user_id = None
        self.current_username = None

    def logout(self) -> None:
        """Log out the current user and clear session state."""
        if self.current_user_id is not None:
            self.auth.logout(self.current_user_id)
        self.current_user_id = None
        self.current_username = None

    def password_change_due(self) -> bool:
        user = self.db.get_user(self._require_user_id())
        if not user:
            return False
        raw = user.get("password_changed_at") or user.get("created_at") or ""
        try:
            changed_at = datetime.fromisoformat(str(raw))
        except ValueError:
            return True
        return datetime.now() - changed_at >= timedelta(
            days=PASSWORD_CHANGE_REMINDER_DAYS,
        )

    def current_user_is_admin(self) -> bool:
        return self.auth.is_admin(self._require_user_id())

    def list_users_for_management(self) -> list[dict]:
        return self.auth.list_users_for_admin(self._require_user_id())

    def admin_reset_password(
        self,
        admin_password: str,
        target_user_id: int,
        new_password: str,
        *,
        clear_remember: bool = True,
    ) -> bool:
        return self.auth.admin_reset_password(
            self._require_user_id(),
            admin_password,
            target_user_id,
            new_password,
            clear_remember=clear_remember,
        )

    def set_user_admin(
        self,
        admin_password: str,
        target_user_id: int,
        enabled: bool,
    ) -> bool:
        return self.auth.set_user_admin(
            self._require_user_id(),
            admin_password,
            target_user_id,
            enabled,
        )

    def regenerate_recovery_key(self, target_username: str) -> str:
        return self.auth.regenerate_recovery_key(
            self._require_user_id(),
            target_username,
        )

    def ensure_default_user_session(self) -> None:
        if self.current_user_id is not None:
            return
        if self.db.user_count() == 0:
            user_id = self.db.create_user(
                DEFAULT_ADMIN_USER,
                DEFAULT_ADMIN_USER,
                is_admin=True,
            )
        else:
            user = self.db.first_user()
            user_id = int(user["id"])
        self.set_current_user(user_id)

    def _require_user_id(self) -> int:
        if self.current_user_id is None:
            raise RuntimeError("login_required")
        return self.current_user_id

    @staticmethod
    def _require_text(value: str, field_name: str) -> str:
        if not isinstance(value, str):
            raise TypeError(f"{field_name}_must_be_string")
        value = value.strip()
        if not value:
            raise ValueError(f"{field_name}_required")
        return value

    def get_setting(self, key: str, default=None):
        return self.db.get_setting(key, default, user_id=self._require_user_id())

    def set_setting(self, key: str, value) -> None:
        self.db.set_setting(key, value, user_id=self._require_user_id())

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
        day = self._require_text(day, "day")
        return self.db.get(day, user_id=self._require_user_id())

    def save_record(self, day, start, end, break_hours, note, work_type="normal", overnight: int | None = None) -> None:
        day = self._require_text(day, "day")
        self.db.save(
            day, start, end, break_hours, note, work_type,
            overnight=overnight,
            user_id=self._require_user_id(),
        )

    def month_records(self, ym: str):
        ym = self._require_text(ym, "month")
        return self.db.month(ym, user_id=self._require_user_id())

    def all_records(self):
        return self.db.all_records(user_id=self._require_user_id())

    def get_data_date_range(self) -> tuple[date | None, date | None]:
        return self.db.get_data_date_range(user_id=self._require_user_id())

    def add_quick_log(self, date_str: str, time_str: str, desc: str, end_time: str = "") -> int:
        return self.db.add_quick_log(
            date_str, time_str, desc, end_time,
            user_id=self._require_user_id(),
        )

    def update_quick_log(self, log_id: int, description: str, time_str: str = "", end_time: str = "") -> None:
        self.db.update_quick_log(
            log_id, description, time_str, end_time,
            user_id=self._require_user_id(),
        )

    def delete_quick_log(self, log_id: int) -> None:
        self.db.delete_quick_log(log_id, user_id=self._require_user_id())

    def quick_logs_for_date(self, date_str: str) -> list[dict]:
        return self.db.get_quick_logs_for_date(
            date_str,
            user_id=self._require_user_id(),
        )

    def quick_logs_for_range(self, start_d: str, end_d: str) -> list[dict]:
        return self.db.get_quick_logs_for_range(
            start_d, end_d,
            user_id=self._require_user_id(),
        )

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
        return self.db.get_calendar_events_for_date(
            day,
            user_id=self._require_user_id(),
        )

    def get_calendar_events_for_range(self, start_d: str, end_d: str) -> list[dict]:
        return self.db.get_calendar_events_for_range(
            start_d, end_d,
            user_id=self._require_user_id(),
        )

    def clear_calendar_events(self) -> None:
        self.db.clear_calendar_events(user_id=self._require_user_id())

    def save_calendar_events(self, events: list, source_file: str = "") -> int:
        return self.db.save_calendar_events(
            events, source_file,
            user_id=self._require_user_id(),
        )

    def parse_calendar_file(self, path: str) -> list[dict]:
        return parse_ics_rich(path)

    def import_csv_file(self, path: str, required_cols: set, default_break: float = 1.0) -> tuple[int, list[str]]:
        return import_csv(
            path,
            self.db,
            required_cols,
            default_break=default_break,
            user_id=self._require_user_id(),
        )

    def export_csv_file(self, path: str, rows: Iterable) -> None:
        export_csv(path, list(rows))

    def export_month_ics(self, ym: str) -> str:
        rows = self.month_records(ym)
        return build_ics(rows)

    def should_remind_backup(self) -> bool:
        self._require_user_id()
        raw = self.get_setting(LAST_BACKUP_KEY, "")
        if not raw:
            return True
        try:
            last = datetime.fromisoformat(str(raw))
        except ValueError:
            return True
        return datetime.now() - last >= timedelta(days=BACKUP_REMINDER_DAYS)

    def backup_database(self, dest_path: str) -> bool:
        self._require_user_id()
        dest = Path(dest_path)
        src = Path(self.db.path)
        if src.resolve(strict=False) == dest.resolve(strict=False):
            raise ValueError("backup_same_path")
        dest.parent.mkdir(parents=True, exist_ok=True)
        previous_backup = self.get_setting(LAST_BACKUP_KEY, None)
        self.set_setting(LAST_BACKUP_KEY, datetime.now().isoformat(timespec="seconds"))
        try:
            self.db.conn.commit()
            shutil.copy2(src, dest)
        except Exception:
            self.set_setting(
                LAST_BACKUP_KEY,
                "" if previous_backup is None else previous_backup,
            )
            raise
        return True

    def validate_restore_database(self, src_path: str) -> bool:
        self._require_user_id()
        src = Path(src_path)
        if not src.is_file():
            raise FileNotFoundError(src_path)
        uri = src.resolve().as_uri() + "?mode=ro"
        username = self.current_username
        with sqlite3.connect(uri, uri=True) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("restore_integrity_failed")
            users_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone()
            if not users_exists:
                raise ValueError("restore_missing_users")
            if username:
                row = conn.execute(
                    "SELECT id FROM users WHERE username=?",
                    (username,),
                ).fetchone()
                if row is None:
                    raise ValueError("restore_user_mismatch")
        return True

    def restore_database(self, src_path: str) -> bool:
        self.validate_restore_database(src_path)
        username = self.current_username
        target = Path(self.db.path)
        source = Path(src_path)
        if target.resolve(strict=False) == source.resolve(strict=False):
            return True
        try:
            self.db.conn.close()
        except Exception:
            pass
        try:
            shutil.copy2(source, target)
        finally:
            self.db = DB(str(target))
            self.auth = AuthService(self.db)
        if username:
            user = self.db.get_user_by_username(username)
            if user:
                self.set_current_user(int(user["id"]), user["username"])
                return True
        self.clear_current_user()
        return False

    def _validate_report_type(self, report_type: str) -> str:
        if report_type not in {"weekly", "monthly"}:
            raise ValueError("invalid_report_type")
        return report_type

    def save_report(
        self,
        report_type: str,
        period_start: str,
        period_end: str,
        content: str,
    ) -> int:
        self._validate_report_type(report_type)
        if not content.strip():
            raise ValueError("empty_report")
        return self.db.save_report(
            report_type,
            period_start,
            period_end,
            content,
            user_id=self._require_user_id(),
        )

    def get_reports_by_type(self, report_type: str) -> list[dict]:
        self._validate_report_type(report_type)
        return self.db.get_reports_by_type(
            report_type,
            user_id=self._require_user_id(),
        )

    def get_report_for_period(
        self,
        report_type: str,
        period_start: str,
        period_end: str,
    ) -> dict | None:
        self._validate_report_type(report_type)
        return self.db.get_report_for_period(
            report_type,
            period_start,
            period_end,
            user_id=self._require_user_id(),
        )

    def delete_report(self, report_id: int) -> None:
        self.db.delete_report(report_id, user_id=self._require_user_id())

    def generate_weekly_report(
        self,
        selected: date,
        work_hours: float,
        lang: str,
        *,
        save_to_db: bool = False,
    ) -> str:
        return report_service.generate_weekly(
            selected,
            self.db,
            work_hours,
            lang,
            user_id=self._require_user_id(),
            save_to_db=save_to_db,
        )

    def generate_monthly_report(
        self,
        year: int,
        month: int,
        work_hours: float,
        lang: str,
        *,
        save_to_db: bool = False,
    ) -> str:
        return report_service.generate_monthly(
            year,
            month,
            self.db,
            work_hours,
            lang,
            user_id=self._require_user_id(),
            save_to_db=save_to_db,
        )

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
            current_user_id=self.current_user_id,
            current_username=self.current_username,
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
            self.set_setting(key, value)

    def set_custom_theme(self, accent_hex: str) -> AppState:
        normalized = set_custom_theme(accent_hex)
        self.set_setting(CUSTOM_THEME_SETTING_KEY, normalized)
        self.set_setting(THEME_SETTING_KEY, "custom")
        return self.load_settings()

    def toggle_minimal_mode(self, enabled: bool) -> AppState:
        self.set_setting(MINIMAL_MODE_SETTING_KEY, "1" if enabled else "0")
        return self.load_settings()

    def load_settings_snapshot(self) -> AppState:
        return self.load_settings()

    # Secret (API key) helpers.
    # API keys are sensitive credentials.  These methods route through
    # key_store which tries the OS keychain first, then Fernet-encrypted DB.

    _SECRET_KEYS = {"ai_api_key", "ai2_api_key"}

    def get_secret(self, name: str) -> str:
        """Return secret *name*, decrypting if stored via key_store."""
        return get_secret(self.db, name, self._require_user_id())

    def set_secret(self, name: str, value: str) -> None:
        """Store secret *name* as securely as the environment allows."""
        set_secret(self.db, name, value, self._require_user_id())

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
