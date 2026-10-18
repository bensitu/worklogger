"""Account-scoped report history queries and lightweight results."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from worklogger.domain.reporting.periods import normalize_report_type


class ReportSort(StrEnum):
    DATE_DESC = "date_desc"
    DATE_ASC = "date_asc"
    SAVED_DESC = "saved_desc"
    SAVED_ASC = "saved_asc"


@dataclass(frozen=True)
class ReportHistoryFilter:
    report_type: str
    start: date
    end: date
    text: str = ""
    sort: ReportSort = ReportSort.DATE_DESC

    def __post_init__(self):
        object.__setattr__(self, "report_type", normalize_report_type(self.report_type))
        object.__setattr__(self, "sort", ReportSort(self.sort))
        if (not isinstance(self.start, date) or not isinstance(self.end, date) or self.start > self.end
                or not isinstance(self.text, str) or len(self.text) > 256):
            raise ValueError("report_history_filter_invalid")


@dataclass(frozen=True)
class ReportHistoryCursor:
    value: str | float
    report_id: int


@dataclass(frozen=True)
class ReportSummary:
    id: int
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    created_at: datetime | None
    revision: int
    updated_at: datetime | None


@dataclass(frozen=True)
class ReportHistoryPage:
    reports: tuple[ReportSummary, ...] = ()
    next_cursor: ReportHistoryCursor | None = None
    total: int = 0
