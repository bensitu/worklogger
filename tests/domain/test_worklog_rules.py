from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from zoneinfo import ZoneInfo
from random import Random
import unittest

from worklogger.domain.worklog.models import TimeRange, WorkLog, EntryType, EntryCategory, CustomEntryType, WorkMode
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.intervals import EntryIntervalIndex
from worklogger.domain.worklog.rules import (
    calc_hours,
    calc_shift_span_hours,
    is_overnight_shift,
    normalize_work_log,
    parse_time,
    shift_datetimes,
    entries_overlap,
)


class WorkLogRuleTests(unittest.TestCase):
    def test_classification_allocations_keep_recorded_duration_and_unknown_arrangements_distinct(self):
        from worklogger.domain.calendar.allocation import allocation_segments, CalendarDimension

        day = date(2026, 10, 18)
        work = WorkLog(1, day, "09:00", "12:00", 1, entry_type=EntryType.MEETING, work_mode=WorkMode.REMOTE)
        rest = WorkLog(1, day, "12:00", "13:00", entry_type=EntryType.BREAK)
        leave = WorkLog(1, day, "13:00", "15:00", entry_type=EntryType.PAID_LEAVE)
        unknown = WorkLog(1, day, "15:00", "16:00")
        records = (work, rest, leave, unknown)
        types = allocation_segments(records)
        self.assertEqual({segment.key: segment.duration for segment in types},
                         {"meeting": 2, "break": 1, "paid_leave": 2, "normal": 1})
        modes = allocation_segments(records, dimension=CalendarDimension.WORK_MODE)
        self.assertEqual({segment.key: segment.duration for segment in modes}, {"remote": 2, "unspecified": 1})
        self.assertEqual(sum(segment.duration for segment in modes), sum(record.worked_hours() for record in records))
        self.assertEqual(allocation_segments(reversed(records)), types)

    def test_classification_allocations_use_historical_leave_fallback_and_stable_custom_ids(self):
        from worklogger.domain.calendar.allocation import allocation_segments

        day = date(2026, 10, 18)
        definition = CustomEntryType("custom:" + "1" * 32, "Research")
        work = WorkLog(1, day, "09:00", "10:00", entry_type=definition)
        renamed = replace(work, start_time="10:00", end_time="11:00", entry_type=replace(definition, label="Study"))
        segment, = allocation_segments((work, renamed))
        self.assertEqual((segment.key, segment.semantic_color_id, segment.duration), (definition.value, definition.value, 2))
        rest = replace(renamed, entry_type=replace(definition, label="Rest", category="break"))
        mixed = allocation_segments((work, rest))
        self.assertEqual({segment.category: segment.duration for segment in mixed}, {EntryCategory.WORK: 1, EntryCategory.BREAK: 1})
        self.assertEqual(allocation_segments((rest, work)), mixed)
        leave = WorkLog(1, day, entry_type=EntryType.SICK_LEAVE)
        self.assertEqual(allocation_segments((leave,), standard_leave_hours=7.5)[0].duration, 7.5)
        self.assertEqual(allocation_segments((WorkLog(1, day, note="Memo"),)), ())

    def test_classification_keeps_accounting_and_optional_work_metadata_separate(self):
        base = WorkLog(1, date(2026, 10, 18), "09:00", "11:00", entry_type=EntryType.MEETING,
                       work_mode=WorkMode.REMOTE)
        self.assertEqual(normalize_work_log(base).worked_hours(), 2)
        self.assertEqual(base.entry_type.category, EntryCategory.WORK)
        for definition in (EntryType.BREAK, EntryType.PAID_LEAVE,
                           CustomEntryType("custom:" + "1" * 32, "Rest", "break")):
            record = replace(base, entry_type=definition, work_mode=None)
            self.assertEqual(normalize_work_log(record).worked_hours(), 0)
            for changes in ({"work_mode": WorkMode.ONSITE}, {"context": WorkContext(project_label="Project")}):
                with self.assertRaisesRegex(ValueError, "entry_classification_invalid"):
                    normalize_work_log(replace(record, **changes))
        with self.assertRaisesRegex(ValueError, "work_mode_invalid"):
            normalize_work_log(replace(base, work_mode="invalid"))
        with self.assertRaisesRegex(ValueError, "entry_type_invalid"):
            normalize_work_log(replace(base, entry_type="unknown"))

    def test_incremental_interval_index_matches_pairwise_rules_in_source_order(self):
        random = Random(17)
        records = []
        for _index in range(250):
            start = datetime(2026, 11, 1, 1) + timedelta(minutes=random.randrange(120))
            end = start + timedelta(minutes=random.randrange(1, 90), seconds=random.randrange(60))
            user = random.choice((1, 2))
            if random.choice((True, False)):
                started = start.replace(tzinfo=timezone(timedelta(hours=random.choice((-4, -5, 9)))))
                ended = (started.astimezone(timezone.utc) + (end - start)).astimezone(
                    timezone(timedelta(hours=random.choice((-4, -5, 9)))))
                records.append(WorkLog(user, started.date(), started.strftime("%H:%M"), ended.strftime("%H:%M"),
                                       started_at=started, ended_at=ended))
            else:
                records.append(WorkLog(user, start.date(), start.strftime("%H:%M"), end.strftime("%H:%M")))
        index, accepted = EntryIntervalIndex(records), []
        for record in records:
            expected = not any(record.user_id == other.user_id and entries_overlap(record, other) for other in accepted)
            self.assertEqual(index.add(record), expected)
            if expected:
                accepted.append(record)

    def test_unknown_offsets_use_wall_clocks_but_captured_offsets_use_elapsed_intervals(self):
        zone = ZoneInfo("America/New_York")
        day = date(2026, 3, 8)
        legacy = WorkLog(1, day, "02:30", "04:00")
        captured = WorkLog(1, day, "03:00", "03:20", started_at=datetime(2026, 3, 8, 3, tzinfo=zone),
                           ended_at=datetime(2026, 3, 8, 3, 20, tzinfo=zone))
        self.assertTrue(entries_overlap(legacy, captured))
        self.assertTrue(entries_overlap(captured, legacy))
        fall = date(2026, 11, 1)
        early = WorkLog(1, fall, "01:10", "01:20", started_at=datetime(2026, 11, 1, 1, 10, tzinfo=zone),
                        ended_at=datetime(2026, 11, 1, 1, 20, tzinfo=zone))
        late = WorkLog(1, fall, "01:10", "01:20", started_at=datetime(2026, 11, 1, 1, 10, tzinfo=zone, fold=1),
                       ended_at=datetime(2026, 11, 1, 1, 20, tzinfo=zone, fold=1))
        self.assertFalse(entries_overlap(early, late))
        self.assertTrue(entries_overlap(WorkLog(1, fall, "01:10", "01:20"), late))

    def test_timer_reminders_use_elapsed_time_and_do_not_treat_rest_or_leave_as_work(self):
        from worklogger.domain.worklog.reminders import timer_reminders
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
        end = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)
        self.assertEqual(timer_reminders(start, end, EntryType.NORMAL, long_hours=2, continuous_hours=1), ("long_timer", "continuous_timer"))
        self.assertEqual(timer_reminders(start, end, EntryType.BREAK, long_hours=0, continuous_hours=1), ())
        self.assertEqual(timer_reminders(start, end, EntryType.PAID_LEAVE, long_hours=0, continuous_hours=1), ())
        late = start.astimezone(timezone.utc) + timedelta(hours=17)
        self.assertEqual(timer_reminders(start, late, EntryType.NORMAL, long_hours=0), ("duration_limit",))

    def test_offset_aware_shifts_preserve_elapsed_hours_across_clock_changes(self) -> None:
        zone = ZoneInfo("America/New_York")
        for day, expected in ((date(2026, 3, 7), 6.0), (date(2026, 10, 31), 8.0)):
            with self.subTest(day=day):
                started, ended = shift_datetimes(day, "22:00", "06:00", zone)
                record = normalize_work_log(WorkLog(1, day, "22:00", "06:00", 1,
                    started_at=started, ended_at=ended))
                self.assertEqual(record.worked_hours(), expected)
                self.assertTrue(record.is_overnight)
                self.assertEqual(record.raw_hours(), expected)
        with self.assertRaises(ValueError):
            shift_datetimes(date(2026, 3, 8), "02:30", "06:00", zone)

    def test_parse_time_accepts_supported_input_formats(self) -> None:
        self.assertEqual(parse_time("9"), "09:00")
        self.assertEqual(parse_time("930"), "09:30")
        self.assertEqual(parse_time("16:30"), "16:30")
        self.assertEqual(parse_time("9:3"), "09:03")
        self.assertIsNone(parse_time("24:00"))
        self.assertIsNone(parse_time("²"))
        self.assertIsNone(parse_time("1.5"))
        self.assertEqual(parse_time("1.50"), "01:50")
        self.assertEqual(parse_time("１２：３０"), "12:30")
        self.assertEqual(parse_time("９３０"), "09:30")
        self.assertEqual(parse_time("９．３０"), "09:30")
        for value in ("1:2:3", "12::30", "１：２：３", "93:0", "1:234"):
            self.assertIsNone(parse_time(value))
        self.assertEqual(parse_time("1: 2"), "01:02")

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
                entry_type=EntryType.NORMAL,
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
                entry_type=EntryType.PAID_LEAVE,
            )
        )
        self.assertTrue(leave.is_leave)
        self.assertEqual(leave.worked_hours(), 0.0)
        self.assertEqual(leave.leave_hours(), 4.0)

        full_day_leave = normalize_work_log(
            WorkLog(
                user_id=1,
                day=date(2026, 4, 22),
                entry_type=EntryType.SICK_LEAVE,
            )
        )
        self.assertEqual(full_day_leave.leave_hours(standard_hours=8.0), 8.0)

    def test_nonfinite_breaks_and_invalid_supplied_times_are_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), 1e9):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_work_log(WorkLog(1, date(2026, 4, 20), break_hours=value))
        with self.assertRaises(ValueError):
            normalize_work_log(WorkLog(1, date(2026, 4, 20), start_time="invalid", end_time="invalid"))


if __name__ == "__main__":
    unittest.main()
