"""SQLite repository adapters."""

from worklogger.infrastructure.repositories.auth_sqlite import (
    SQLiteAuthRepository,
    SQLiteIdentityRepository,
    SQLiteLoginFailureRepository,
)
from worklogger.infrastructure.repositories.audit_sqlite import AuditEvent, SQLiteAuditRepository
from worklogger.infrastructure.repositories.calendar_sqlite import SQLiteCalendarEventRepository
from worklogger.infrastructure.repositories.note_sqlite import SQLiteDailyNoteRepository
from worklogger.infrastructure.repositories.quicklog_sqlite import SQLiteQuickLogRepository
from worklogger.infrastructure.repositories.report_sqlite import SQLiteReportRepository
from worklogger.infrastructure.repositories.settings_sqlite import SQLiteSettingsRepository
from worklogger.infrastructure.repositories.template_sqlite import SQLiteReportTemplateRepository
from worklogger.infrastructure.repositories.worklog_sqlite import SQLiteWorkLogRepository

__all__ = [
    "AuditEvent",
    "SQLiteAuthRepository",
    "SQLiteAuditRepository",
    "SQLiteCalendarEventRepository",
    "SQLiteDailyNoteRepository",
    "SQLiteIdentityRepository",
    "SQLiteLoginFailureRepository",
    "SQLiteQuickLogRepository",
    "SQLiteReportRepository",
    "SQLiteReportTemplateRepository",
    "SQLiteSettingsRepository",
    "SQLiteWorkLogRepository",
]
