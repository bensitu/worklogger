from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import unittest
from zoneinfo import ZoneInfo

from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.editing import split_entry, split_entry_at, merge_entries
from worklogger.domain.worklog.models import WorkLog, EntryType, WorkMode
from worklogger.domain.worklog.replacement import EntryReplacement


class RecordReplacementTests(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 10, 5)
        self.old = WorkLog(1, self.day, "09:00", "18:00", note="Planning", entry_type=EntryType.MEETING,
                           id=10, revision=2, context=WorkContext(project_label="Research"), work_mode=WorkMode.REMOTE)

    def test_replacement_preserves_unaffected_periods_and_metadata(self):
        for start, end, expected in (
            ("12:00", "13:00", [("09:00", "12:00"), ("13:00", "18:00")]),
            ("08:00", "12:00", [("12:00", "18:00")]),
            ("17:00", "19:00", [("09:00", "17:00")]),
            ("09:00", "18:00", []),
        ):
            with self.subTest(start=start, end=end):
                incoming = WorkLog(1, self.day, start, end, entry_type=EntryType.BREAK)
                plan = EntryReplacement(incoming, (self.old,))
                first, *remaining = plan.periods(keep_outside=True)
                self.assertEqual(first, incoming)
                self.assertEqual([(item.start_time, item.end_time) for item in remaining], expected)
                for index, item in enumerate(remaining):
                    self.assertEqual((item.note, item.context, item.entry_type, item.work_mode),
                                     (self.old.note, self.old.context, self.old.entry_type, self.old.work_mode))
                    self.assertEqual(item.id, self.old.id if index == 0 else None)
                self.assertEqual(plan.periods(keep_outside=False), (incoming,))

    def test_merging_requires_matching_arrangement(self):
        left, right = split_entry_at(self.old, datetime(2026, 10, 5, 12))
        self.assertEqual(merge_entries(left, right).work_mode, WorkMode.REMOTE)
        with self.assertRaisesRegex(ValueError, "record_merge_invalid"):
            merge_entries(left, replace(right, work_mode=WorkMode.ONSITE))

    def test_overnight_replacement_keeps_the_correct_dates(self):
        from worklogger.domain.worklog.rules import shift_datetimes

        for day in (date(2026, 10, 31), date(2026, 12, 31), date(2028, 2, 29)):
            tomorrow = day + timedelta(days=1)
            for zone in (None, timezone.utc):
                old_start, old_end = shift_datetimes(day, "22:00", "06:00", zone)
                old = replace(self.old, day=day, start_time="22:00", end_time="06:00",
                              started_at=old_start if zone else None, ended_at=old_end if zone else None)
                for offset, start, end, expected, hours in (
                    (0, "23:00", "23:30", [(day, "22:00", "23:00"), (day, "23:30", "06:00")], 7.5),
                    (0, "23:30", "00:30", [(day, "22:00", "23:30"), (tomorrow, "00:30", "06:00")], 7),
                    (1, "00:00", "01:00", [(day, "22:00", "00:00"), (tomorrow, "01:00", "06:00")], 7),
                    (1, "05:00", "07:00", [(day, "22:00", "05:00")], 7),
                    (0, "21:00", "23:00", [(day, "23:00", "06:00")], 7),
                    (0, "22:00", "06:00", [], 0),
                ):
                    with self.subTest(day=day, zone=zone, start=start, end=end):
                        incoming_day = day + timedelta(days=offset)
                        cut_start, cut_end = shift_datetimes(incoming_day, start, end, zone)
                        incoming = WorkLog(1, incoming_day, start, end, entry_type=EntryType.BREAK,
                                           started_at=cut_start if zone else None, ended_at=cut_end if zone else None)
                        _, *remaining = EntryReplacement(incoming, (old,)).periods(keep_outside=True)
                        self.assertEqual([(item.day, item.start_time, item.end_time) for item in remaining], expected)
                        self.assertEqual(sum(item.worked_hours() for item in remaining), hours)

    def test_historical_deductions_and_full_day_records_are_not_guessed(self):
        incoming = WorkLog(1, self.day, "12:00", "13:00", entry_type=EntryType.BREAK)
        for old, code in ((replace(self.old, break_hours=1), "historical_break_placement_required"),
                          (replace(self.old, start_time=None, end_time=None, entry_type=EntryType.PAID_LEAVE,
                                   context=WorkContext(), work_mode=None),
                           "record_replacement_requires_times")):
            plan = EntryReplacement(incoming, (old,))
            with self.assertRaisesRegex(ValueError, code):
                plan.periods(keep_outside=True)
            self.assertEqual(plan.periods(keep_outside=False), (incoming,))
        cover = replace(incoming, start_time="09:00", end_time="18:00")
        self.assertEqual(EntryReplacement(cover, (replace(self.old, break_hours=1),)).periods(keep_outside=True), (cover,))

    def test_captured_daylight_saving_boundaries_use_elapsed_time(self):
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
        old = replace(self.old, day=start.date(), start_time="00:30", end_time="03:30",
                      started_at=start, ended_at=start.replace(hour=3))
        incoming = WorkLog(1, start.date(), "01:15", "01:45", entry_type=EntryType.BREAK,
                           started_at=start.replace(hour=1, minute=15, fold=1),
                           ended_at=start.replace(hour=1, minute=45, fold=1))
        _, left, right = EntryReplacement(incoming, (old,)).periods(keep_outside=True)
        self.assertEqual(left.worked_hours() + right.worked_hours(), 3.5)
        self.assertEqual(left.ended_at.astimezone(timezone.utc), incoming.started_at.astimezone(timezone.utc))
        with self.assertRaisesRegex(ValueError, "record_replacement_timezone_ambiguous"):
            EntryReplacement(replace(incoming, started_at=None, ended_at=None), (old,)).periods(keep_outside=True)
        old = replace(old, start_time="01:15", started_at=start.replace(hour=1, minute=15, fold=0))
        cut = old.started_at.replace(fold=1)
        left, right = split_entry_at(old, cut)
        self.assertEqual((left.worked_hours(), right.worked_hours()), (1, 2.25))
        self.assertEqual(right.started_at.astimezone(timezone.utc), cut.astimezone(timezone.utc))

    def test_split_accepts_clock_boundaries_and_rejects_endpoints(self):
        cut = datetime.combine(self.day, datetime.min.time()).replace(hour=12)
        left, right = split_entry_at(self.old, cut)
        self.assertEqual((left.end_time, right.start_time, left.id, right.id), ("12:00", "12:00", 10, None))
        for invalid in (None, cut.replace(hour=9), cut.replace(hour=18), cut.replace(second=30),
                        cut.replace(tzinfo=timezone.utc)):
            with self.assertRaisesRegex(ValueError, "record_split_invalid"):
                split_entry_at(self.old, invalid)

    def test_elapsed_splits_and_replacements_keep_fixed_offset_policy(self):
        start = datetime.fromisoformat("2026-11-01T00:30:00-04:00")
        end = datetime.fromisoformat("2026-11-01T03:30:00-05:00")
        old = replace(self.old, day=start.date(), start_time="00:30", end_time="03:30",
                      started_at=start, ended_at=end)
        left, right = split_entry(old, 135)
        self.assertEqual(left.ended_at.isoformat(), "2026-11-01T02:45:00-04:00")
        self.assertEqual(right.started_at.isoformat(), left.ended_at.isoformat())
        self.assertEqual((left.started_at.isoformat(), right.ended_at.isoformat()),
                         (start.isoformat(), end.isoformat()))
        self.assertEqual(left.worked_hours() + right.worked_hours(), old.worked_hours())

        incoming = WorkLog(1, start.date(), "01:45", "02:00", entry_type=EntryType.BREAK,
                           started_at=datetime.fromisoformat("2026-11-01T01:45:00-05:00"),
                           ended_at=datetime.fromisoformat("2026-11-01T02:00:00-05:00"))
        _, left, right = EntryReplacement(incoming, (old,)).periods(keep_outside=True)
        self.assertEqual(left.ended_at.isoformat(), "2026-11-01T02:45:00-04:00")
        self.assertEqual(right.started_at.isoformat(), "2026-11-01T03:00:00-04:00")
        self.assertEqual(left.worked_hours() + right.worked_hours(), old.worked_hours() - incoming.raw_hours())

    def test_replacement_rejects_foreign_and_duplicate_records(self):
        incoming = WorkLog(1, self.day, "12:00", "13:00")
        for records in ((replace(self.old, user_id=2),), (self.old, self.old), (replace(self.old, id=None),)):
            with self.assertRaisesRegex(ValueError, "record_batch_invalid"):
                EntryReplacement(incoming, records).periods(keep_outside=True)
