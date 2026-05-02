"""Application-wide constants — single source of truth."""

APP_VERSION = "3.2.0"
APP_AUTHOR = "Ben Situ"
APP_ID = "dev.worklogger.app.v1"
GITHUB_URL = "https://github.com/bensitu/worklogger"
GITHUB_RELEASES_API = (
    "https://api.github.com/repos/bensitu/worklogger/releases/latest"
)
MODEL_CATALOG_REMOTE_FILENAME = "model_catalog.json"
MODEL_CATALOG_REMOTE_URL = (
    "https://raw.githubusercontent.com/bensitu/worklogger/main/"
    + MODEL_CATALOG_REMOTE_FILENAME
)
MODEL_CATALOG_FETCH_TIMEOUT_SECONDS = 8
MODEL_CATALOG_FETCH_RETRY_ATTEMPTS = 2
MODEL_CATALOG_FETCH_RETRY_BACKOFF_SECONDS = 0.25
MODEL_CATALOG_RESPONSE_MAX_BYTES = 512 * 1024
MODEL_CATALOG_LOCAL_PRESERVED_KEY = "_local_preserved"
UPDATE_CHECK_TIMEOUT_SECONDS = 8
UPDATE_CHECK_RETRY_ATTEMPTS = 2
UPDATE_CHECK_RETRY_BACKOFF_SECONDS = 0.25
UPDATE_CHECK_CIRCUIT_FAILURES = 3
UPDATE_CHECK_CIRCUIT_COOLDOWN_SECONDS = 300
UPDATE_RESPONSE_MAX_BYTES = 512 * 1024
GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.html"

ASSETS_DIR_NAME = "assets"
FONTS_DIR_NAME = "fonts"
FONT_EN = "NotoSans-Regular.otf"
FONT_JA = "NotoSansJP-Regular.otf"
FONT_KO = "NotoSansKR-Regular.otf"
FONT_ZH_CN = "NotoSansSC-Regular.otf"
FONT_ZH_TW = "NotoSansTC-Regular.otf"
LANGUAGE_FONT_FILES = {
    "en_US": FONT_EN,
    "ja_JP": FONT_JA,
    "ko_KR": FONT_KO,
    "zh_CN": FONT_ZH_CN,
    "zh_TW": FONT_ZH_TW,
}
DEFAULT_LANGUAGE_FONT = FONT_EN
DEFAULT_UI_FONT_POINT_SIZE = 10

DB_FILENAME = "worklog.db"
LOG_FILENAME = "worklogger.log"
MAX_SHIFT_HOURS = 16.0
DEFAULT_LEAVE_HOURS = 8.0

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
AI_PRIVACY_MODE_SETTING_KEY = "ai_privacy_mode"
AI_INCLUDE_NOTES_SETTING_KEY = "ai_context_include_notes"
AI_INCLUDE_CALENDAR_TITLES_SETTING_KEY = "ai_context_include_calendar_titles"
AI_INCLUDE_QUICK_LOG_DETAILS_SETTING_KEY = "ai_context_include_quick_log_details"
OAUTH_LOGIN_ENABLED_SETTING_KEY = "oauth_login_enabled"
GOOGLE_LOGIN_ENABLED_SETTING_KEY = "google_login_enabled"
MICROSOFT_LOGIN_ENABLED_SETTING_KEY = "microsoft_login_enabled"

CUSTOM_THEME_SETTING_KEY = "custom_theme_color"
MINIMAL_MODE_SETTING_KEY = "minimal_mode"
MINIMAL_DATE_NAV_BUTTON_SIZE = 34
MINIMAL_DATE_NAV_FEEDBACK_MS = 120
ANALYTICS_SHOW_LEAVES_SETTING_KEY = "analytics_show_leaves"
COMBO_CHART_VALUE_LABEL_PADDING_X = 5
COMBO_CHART_VALUE_LABEL_PADDING_Y = 2
COMBO_CHART_VALUE_LABEL_GAP = 4
COMBO_CHART_VALUE_LABEL_RADIUS = 4
COMBO_CHART_VALUE_LABEL_LIGHTNESS_THRESHOLD = 160
REMEMBER_TOKEN_KEY = "remember_token"
REMEMBER_SERVICE_NAME = "WorkLogger"
REMEMBER_ACTIVE_USER_KEY = "__active_user__"
REMEMBER_FALLBACK_FILENAME = ".worklogger_remember"
REMEMBER_FILE_PREFIX_V1 = "enc1:"
REMEMBER_FILE_PREFIX_V2 = "enc2:"
DEFAULT_ADMIN_USER = "admin"
FORCE_PASSWORD_CHANGE_SETTING_KEY = "force_password_change"
PASSWORD_MIN_LENGTH = 8
GENERATED_PASSWORD_TOKEN_BYTES = 12
USER_INITIAL_PASSWORD_FILENAME_PREFIX = "worklogger-initial-password"
USER_MANAGEMENT_COLUMN_COUNT = 9
USER_MANAGEMENT_ACTION_COLUMN = 8
USER_MANAGEMENT_ACTION_COLUMN_WIDTH = 520
USER_MANAGEMENT_ROW_HEIGHT = 48
REMEMBER_TOKEN_LIFETIME_DAYS = 30
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
