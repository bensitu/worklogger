from __future__ import annotations

from datetime import date
import unittest

from worklogger.app.queries.calendar_queries import GetHolidaysForRangeQuery
from worklogger.app.queries.work_log_queries import GetMonthRecordsQuery
from worklogger.domain.calendar.models import Holiday
from worklogger.domain.shared.result import Result
from worklogger.domain.worklog.models import WorkLog
from worklogger.presentation.viewmodels import CalendarDisplayOptions, CalendarViewModel


class EmptyMonthRecordsHandler:
    def handle(self, query: GetMonthRecordsQuery) -> Result[tuple[WorkLog, ...]]:
        return Result.success(())


class RecordingHolidaysHandler:
    def __init__(self) -> None:
        self.queries: list[GetHolidaysForRangeQuery] = []

    def handle(
        self,
        query: GetHolidaysForRangeQuery,
    ) -> Result[tuple[Holiday, ...]]:
        self.queries.append(query)
        return Result.success(
            (
                Holiday(day=date(2026, 5, 4), name="Greenery Day"),
            )
        )


class CalendarPresentationTests(unittest.TestCase):
    def test_calendar_viewmodel_loads_holidays_when_enabled(self) -> None:
        holidays = RecordingHolidaysHandler()
        view_model = CalendarViewModel(
            user_id=1,
            month_records_handler=EmptyMonthRecordsHandler(),
            holidays_handler=holidays,
            holiday_country="jp",
        )

        result = view_model.build_month(
            year=2026,
            month=5,
            selected_day=date(2026, 5, 1),
            today=date(2026, 5, 1),
            options=CalendarDisplayOptions(show_holidays=True),
        )

        self.assertTrue(result.ok, result.error)
        assert result.value is not None
        holiday = next(cell for cell in result.value.cells if cell.day == date(2026, 5, 4))
        self.assertTrue(holiday.is_holiday)
        self.assertEqual(holiday.holiday_name, "Greenery Day")
        self.assertEqual(len(holidays.queries), 1)
        self.assertEqual(holidays.queries[0].country, "JP")

    def test_calendar_viewmodel_skips_holiday_handler_when_disabled(self) -> None:
        holidays = RecordingHolidaysHandler()
        view_model = CalendarViewModel(
            user_id=1,
            month_records_handler=EmptyMonthRecordsHandler(),
            holidays_handler=holidays,
        )

        result = view_model.build_month(
            year=2026,
            month=5,
            selected_day=date(2026, 5, 1),
            today=date(2026, 5, 1),
            options=CalendarDisplayOptions(show_holidays=False),
        )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(holidays.queries, [])


if __name__ == "__main__":
    unittest.main()
