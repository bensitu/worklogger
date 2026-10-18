from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import unittest

from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.models import CustomEntryType, EntryType, WorkMode
from worklogger.domain.worklog.timer_state import EntryTimer, decode_timer, encode_timer


class TimerStateTests(unittest.TestCase):
    def test_round_trip_preserves_recording_and_historical_break_fields(self):
        start = datetime(2026, 5, 20, 9, tzinfo=timezone(timedelta(hours=9)))
        custom = CustomEntryType("custom:" + "1" * 32, "Research", "work")
        base = EntryTimer("capture", start, EntryType.NORMAL, "Draft")
        for timer in (base, replace(base, entry_type=custom, context=WorkContext(project_label="Previous project")),
                      replace(base, entry_type=EntryType.BREAK),
                      replace(base, entry_type=CustomEntryType("custom:" + "2" * 32, "Rest", "break"),
                              pending_end=start + timedelta(minutes=30)),
                      replace(base, entry_type=EntryType.BREAK, break_until=start + timedelta(hours=1),
                              resume_type=custom, resume_content="Resume draft", legacy_break_hours=0.5),
                      replace(base, pending_end=start + timedelta(hours=2), work_mode=WorkMode.REMOTE)):
            with self.subTest(timer=timer.entry_type):
                self.assertEqual(decode_timer(encode_timer(timer)), timer)
        self.assertIsNone(encode_timer(None))

    def test_original_timer_keys_preserve_legacy_classification_and_known_arrangement(self):
        payload = {"capture_id": "original", "started_at": "2026-05-20T09:00:00+09:00", "work_type": "remote"}
        timer = decode_timer(json.dumps(payload))
        self.assertEqual(timer.entry_type, EntryType.REMOTE)
        self.assertEqual(timer.work_mode, WorkMode.REMOTE)
        self.assertEqual(decode_timer(encode_timer(timer)), timer)

    def test_recovery_accepts_older_optional_fields_and_rejects_invalid_breaks(self):
        payload = {"capture_id": "previous-capture", "started_at": "2026-05-20T09:00:00+09:00", "entry_type": "normal"}
        timer = decode_timer(json.dumps(payload))
        self.assertEqual(timer.context, WorkContext())
        self.assertEqual(timer.content, "")
        for changes in ({"started_at": "2026-05-20T09:00:00"}, {"legacy_break_hours": 17},
                        {"entry_type": None}, {"unexpected": True}, {"legacy_break_hours": "1"},
                        {"legacy_break_hours": True}, {"context": {"unknown": "value"}},
                        {"entry_type": "paid_leave"}, {"entry_type": "break", "work_mode": "remote"},
                        {"entry_type": "break", "context": {"project_label": "Previous project"}},
                        {"break_until": "2026-05-20T10:00:00+09:00"},
                        {"entry_type": "break", "resume_type": "normal", "break_until": "2026-05-20T14:00:00+09:00"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "^auto_record_restore_failed$"):
                decode_timer(json.dumps(payload | changes))
