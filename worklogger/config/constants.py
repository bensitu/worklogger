"""Stable domain and application defaults."""

from __future__ import annotations

MAX_SHIFT_HOURS = 16.0
DEFAULT_LEAVE_HOURS = 8.0

WORK_TYPE_KEYS = (
    "normal",
    "remote",
    "business_trip",
    "paid_leave",
    "comp_leave",
    "sick_leave",
)
LEAVE_TYPES = frozenset({"paid_leave", "comp_leave", "sick_leave"})

PASSWORD_MIN_LENGTH = 8
GENERATED_PASSWORD_TOKEN_BYTES = 12
RECOVERY_KEY_BYTES = 24
RECOVERY_KEY_GROUP_SIZE = 8

REMEMBER_TOKEN_LIFETIME_DAYS = 30
REMEMBER_TOKEN_HASH_PREFIX = "sha256:"

LOGIN_FAILURE_LOCK_THRESHOLD = 5
LOGIN_LOCKOUT_SECONDS = 30
LOGIN_LOCKOUT_SCHEDULE = (
    (5, 30),
    (10, 300),
    (15, 1800),
    (20, 86400),
)

FORCE_PASSWORD_CHANGE_SETTING_KEY = "force_password_change"
LOCAL_MODEL_ACTIVE_ID_SETTING_KEY = "local_model_active_id"
LOCAL_MODEL_ENABLED_SETTING_KEY = "local_model_enabled"

THEME_SETTING_KEY = "theme"
CUSTOM_THEME_COLOR_SETTING_KEY = "custom_theme_color"
DARK_MODE_SETTING_KEY = "dark_mode"
AI_ASSIST_ENABLED_SETTING_KEY = "ai_assist_enabled"
AI_PRIVACY_INCLUDE_NOTES_SETTING_KEY = "ai_privacy_include_notes"
AI_PRIVACY_INCLUDE_CALENDAR_SETTING_KEY = "ai_privacy_include_calendar"
AI_PRIVACY_INCLUDE_QUICK_LOGS_SETTING_KEY = "ai_privacy_include_quick_logs"
MINIMAL_MODE_SETTING_KEY = "minimal_mode"
STANDARD_WORK_HOURS_SETTING_KEY = "standard_work_hours"
DEFAULT_BREAK_HOURS_SETTING_KEY = "default_break_hours"
MONTHLY_TARGET_HOURS_SETTING_KEY = "monthly_target_hours"
SHOW_HOLIDAYS_SETTING_KEY = "show_holidays"
SHOW_NOTE_MARKERS_SETTING_KEY = "show_note_markers"
SHOW_OVERNIGHT_INDICATOR_SETTING_KEY = "show_overnight_indicator"
WEEK_START_MONDAY_SETTING_KEY = "week_start_monday"
ENABLE_TRAY_SETTING_KEY = "enable_tray"
ENABLE_MENU_BAR_SETTING_KEY = "enable_menu_bar"

DB_FILENAME = "worklog.db"
DB_CORRUPT_BACKUP_RETENTION = 3
ICS_MAX_BYTES = 10 * 1024 * 1024

TZ_COUNTRY = {
    "Asia/Tokyo": "JP",
    "Asia/Seoul": "KR",
    "Asia/Shanghai": "CN",
    "Asia/Hong_Kong": "HK",
    "Asia/Singapore": "SG",
    "Asia/Taipei": "TW",
    "Asia/Bangkok": "TH",
    "Asia/Jakarta": "ID",
    "Asia/Kolkata": "IN",
    "Asia/Dubai": "AE",
    "Europe/London": "GB",
    "Europe/Paris": "FR",
    "Europe/Berlin": "DE",
    "Europe/Rome": "IT",
    "Europe/Madrid": "ES",
    "Europe/Amsterdam": "NL",
    "Europe/Stockholm": "SE",
    "Europe/Oslo": "NO",
    "Europe/Helsinki": "FI",
    "Europe/Warsaw": "PL",
    "Europe/Zurich": "CH",
    "Europe/Vienna": "AT",
    "Europe/Brussels": "BE",
    "Europe/Lisbon": "PT",
    "America/New_York": "US",
    "America/Chicago": "US",
    "America/Denver": "US",
    "America/Los_Angeles": "US",
    "America/Toronto": "CA",
    "America/Vancouver": "CA",
    "America/Sao_Paulo": "BR",
    "America/Mexico_City": "MX",
    "Australia/Sydney": "AU",
    "Australia/Melbourne": "AU",
    "Pacific/Auckland": "NZ",
}

SECRET_SETTING_PREFIX = "secret:"
MACHINE_KEY_FILENAME = ".worklogger_machine_key"
KEYRING_SERVICE_NAME = "WorkLogger"
GITHUB_LATEST_RELEASE_API_URL = "https://api.github.com/repos/bensitu/worklogger/releases/latest"
LOG_BACKUP_COUNT = 5
LOG_FILENAME = "worklogger.log"
LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"
LOG_MAX_BYTES = 1_000_000
