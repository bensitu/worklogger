"""Application-wide constants — single source of truth."""

import sys

APP_VERSION = "2.2.0"
APP_NAME = "Work Logger"
APP_AUTHOR = "Ben Situ"
APP_ID = "dev.worklogger.app.v2"
GITHUB_URL = "https://github.com/bensitu/worklogger"
GITHUB_RELEASES_API = (
    "https://api.github.com/repos/bensitu/worklogger/releases/latest"
)
GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.html"
LICENSE_SPDX = "GPL-3.0-or-later"

DB_FILENAME = "worklog.db"
MAX_SHIFT_HOURS = 16.0

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
