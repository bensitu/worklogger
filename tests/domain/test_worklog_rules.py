from __future__ import annotations

from datetime import date
import unittest

from worklogger.domain.worklog.models import TimeRange, WorkLog, WorkType
from worklogger.domain.worklog.rules import (
    calc_hours,
    calc_shift_span_hours,
    is_overnight_shift,
    normalize_work_log,
    parse_time,
    shift_datetimes,
)


class WorkLogRuleTests(unittest.TestCase):
    def test_parse_time_accepts_baseline_flexible_inputs(self) -> None:
        self.assertEqual(parse_time("9"), "09:00")
        self.assertEqual(parse_time("930"), "09:30")
        self.assertEqual(parse_time("16:30"), "16:30")
        self.assertEqual(parse_time("9:3"), "09:03")
        self.assertIsNone(parse_time("24:00"))

    def test_overnight_calculation_and_shift_datetimes(self) -> None:
        self.assertTrue(is_overnight_shift("22:00", "09:00"))
        self.assertEqual(calc_shift_span_hours("22:00", "09:00"), 11.0)
        self.assertEqual(calc_hours("22:00", "09:00", 1.0), 10.0)
        self.assertIsNone(calc_shift_span_hours("20:00", "13:00"))

        start_dt, end_dt = shift_datetimes(date(2026, 4, 20), "22:00", "09:00") or (None, None)
        self.assertEqual(start_dt.strftime("%Y-%m-%d %H:%M"), "2026-04-20 22:00")
        self.assertEqual(end_dt.strftime("%Y-%m-%d %H:%M"), "2026-04-21 09:00")

    def test_time_range_value_object_delegates_to_rules(self) -> None:
        time_range = TimeRange("22:00", "09:00")
        self.assertTrue(time_range.overnight)
        self.assertEqual(time_range.span_hours(), 11.0)

    def test_normalize_work_log_validates_breaks_and_marks_overnight(self) -> None:
        record = normalize_work_log(
            WorkLog(
                user_id=1,
                day=date(2026, 4, 20),
                start_time="2200",
                end_time="0900",
                break_hours=1.0,
                work_type=WorkType.NORMAL,
            )
        )
        self.assertEqual(record.start_time, "22:00")
        self.assertEqual(record.end_time, "09:00")
        self.assertTrue(record.is_overnight)
        self.assertEqual(record.worked_hours(), 10.0)

        with self.assertRaises(ValueError):
            normalize_work_log(
                WorkLog(
                    user_id=1,
                    day=date(2026, 4, 20),
                    start_time="09:00",
                    end_time=None,
                )
            )

        with self.assertRaises(ValueError):
            normalize_work_log(
                WorkLog(
                    user_id=1,
                    day=date(2026, 4, 20),
                    start_time="09:00",
                    end_time="10:00",
                    break_hours=1.0,
                )
            )

    def test_leave_records_do_not_count_as_work_hours(self) -> None:
        leave = normalize_work_log(
            WorkLog(
                user_id=1,
                day=date(2026, 4, 21),
                start_time="09:00",
                end_time="13:00",
                break_hours=0.0,
                work_type=WorkType.PAID_LEAVE,
            )
        )
        self.assertTrue(leave.is_leave)
        self.assertEqual(leave.worked_hours(), 0.0)
        self.assertEqual(leave.leave_hours(), 4.0)

        full_day_leave = normalize_work_log(
            WorkLog(
                user_id=1,
                day=date(2026, 4, 22),
                work_type=WorkType.SICK_LEAVE,
            )
        )
        self.assertEqual(full_day_leave.leave_hours(standard_hours=8.0), 8.0)


if __name__ == "__main__":
    unittest.main()
