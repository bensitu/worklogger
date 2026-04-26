"""Application-wide constants — single source of truth."""

import sys

APP_VERSION = "3.0.0"
APP_NAME = "Work Logger"
APP_AUTHOR = "Ben Situ"
APP_ID = "dev.worklogger.app.v1"
GITHUB_URL = "https://github.com/bensitu/worklogger"
GITHUB_RELEASES_API = (
    "https://api.github.com/repos/bensitu/worklogger/releases/latest"
)
GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.html"
LICENSE_SPDX = "GPL-3.0-or-later"

DB_FILENAME = "worklog.db"
LOG_FILENAME = "worklogger.log"
MAX_SHIFT_HOURS = 16.0

LANG_SETTING_KEY = "lang"
THEME_SETTING_KEY = "theme"
DARK_MODE_SETTING_KEY = "dark"
WORK_HOURS_SETTING_KEY = "work_hours"
DEFAULT_BREAK_SETTING_KEY = "default_break"
LEGACY_DEFAULT_BREAK_SETTING_KEY = "default_lunch"
MONTHLY_TARGET_SETTING_KEY = "monthly_target"
SHOW_HOLIDAYS_SETTING_KEY = "show_holidays"
SHOW_NOTE_MARKERS_SETTING_KEY = "show_note_markers"
SHOW_OVERNIGHT_INDICATOR_SETTING_KEY = "show_overnight_indicator"
WEEK_START_MONDAY_SETTING_KEY = "week_start_monday"
TIME_INPUT_MODE_SETTING_KEY = "time_input_mode"
MAX_SHIFT_HOURS_SETTING_KEY = "max_shift_hours"
LOCAL_MODEL_ENABLED_SETTING_KEY = "local_model_enabled"

CUSTOM_THEME_SETTING_KEY = "custom_theme_color"
MINIMAL_MODE_SETTING_KEY = "minimal_mode"
MINIMAL_DATE_NAV_BUTTON_SIZE = 34
MINIMAL_DATE_NAV_FEEDBACK_MS = 120
ANALYTICS_SHOW_LEAVES_SETTING_KEY = "analytics_show_leaves"
REMEMBER_TOKEN_KEY = "remember_token"
REMEMBER_SERVICE_NAME = "WorkLogger"
REMEMBER_ACTIVE_USER_KEY = "__active_user__"
REMEMBER_STORE_KEYRING = "keyring"
REMEMBER_STORE_FERNET_FILE = "fernet_file"
REMEMBER_FALLBACK_FILENAME = ".worklogger_remember"
REMEMBER_FILE_PREFIX_V1 = "enc1:"
REMEMBER_FILE_PREFIX_V2 = "enc2:"
DEFAULT_ADMIN_USER = "admin"
FORCE_PASSWORD_CHANGE_SETTING_KEY = "force_password_change"
PASSWORD_CHANGE_REMINDER_DAYS = 90
BACKUP_REMINDER_DAYS = 30
LAST_BACKUP_KEY = "last_backup_timestamp"

WORK_TYPE_KEYS = [
    "normal", "remote", "business_trip",
    "paid_leave", "comp_leave", "sick_leave",
]
LEAVE_TYPES = {"paid_leave", "comp_leave", "sick_leave"}

TZ_COUNTRY = {
    "Asia/Tokyo": "JP", "Asia/Seoul": "KR", "Asia/Shanghai": "CN",
    "Asia/Hong_Kong": "HK", "Asia/Singapore": "SG", "Asia/Taipei": "TW",
    "Asia/Bangkok": "TH", "Asia/Jakarta": "ID", "Asia/Kolkata": "IN",
    "Asia/Dubai": "AE", "Europe/London": "GB", "Europe/Paris": "FR",
    "Europe/Berlin": "DE", "Europe/Rome": "IT", "Europe/Madrid": "ES",
    "Europe/Amsterdam": "NL", "Europe/Stockholm": "SE", "Europe/Oslo": "NO",
    "Europe/Helsinki": "FI", "Europe/Warsaw": "PL", "Europe/Zurich": "CH",
    "Europe/Vienna": "AT", "Europe/Brussels": "BE", "Europe/Lisbon": "PT",
    "America/New_York": "US", "America/Chicago": "US", "America/Denver": "US",
    "America/Los_Angeles": "US", "America/Toronto": "CA", "America/Vancouver": "CA",
    "America/Sao_Paulo": "BR", "America/Mexico_City": "MX",
    "Australia/Sydney": "AU", "Australia/Melbourne": "AU", "Pacific/Auckland": "NZ",
}
