import os
import sys
import unittest
from datetime import date


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from core.models import WorkRecord
from core.time_calc import (
    calc_hours,
    calc_shift_span_hours,
    is_overnight_shift,
    shift_datetimes,
)
from services.export_service import build_ics
from services import report_service
from utils.i18n import LANG_NAMES, get_translator


class OvernightShiftLogicTests(unittest.TestCase):
    def test_calc_hours_supports_overnight(self):
        self.assertEqual(calc_hours("22:00", "09:00", 1.0), 10.0)

    def test_calc_shift_span_rejects_too_long_shift(self):
        self.assertIsNone(calc_shift_span_hours("20:00", "13:00"))  # 17h > 16h
        self.assertEqual(calc_hours("20:00", "13:00", 1.0), 0.0)

    def test_detect_overnight(self):
        self.assertTrue(is_overnight_shift("22:00", "09:00"))
        self.assertFalse(is_overnight_shift("09:00", "18:00"))

    def test_shift_datetimes_rolls_end_to_next_day(self):
        start_dt, end_dt = shift_datetimes("2026-04-20", "22:00", "09:00")
        self.assertEqual(start_dt.strftime("%Y-%m-%d %H:%M"), "2026-04-20 22:00")
        self.assertEqual(end_dt.strftime("%Y-%m-%d %H:%M"), "2026-04-21 09:00")

    def test_ics_export_uses_next_day_end_for_overnight(self):
        rows = [
            WorkRecord(
                date="2026-04-20",
                start="22:00",
                end="09:00",
                break_hours=1.0,
                note="Night shift",
                work_type="normal",
            )
        ]
        ics = build_ics(rows)
        self.assertIn("DTSTART:20260420T220000", ics)
        self.assertIn("DTEND:20260421T090000", ics)

    def test_ics_export_escapes_text_and_folds_long_lines(self):
        rows = [
            WorkRecord(
                date="2026-04-20",
                start="09:00",
                end="18:00",
                break_hours=1.0,
                note="Alpha; Beta, Gamma\\Delta\n" + ("x" * 120),
                work_type="normal",
            )
        ]
        ics = build_ics(rows)
        self.assertIn(r"Alpha\; Beta\, Gamma\\Delta\n", ics)
        for line in ics.split("\r\n"):
            if line:
                self.assertLessEqual(len(line.encode("utf-8")), 75)

    def test_report_line_contains_overnight_marker(self):
        class _FakeDB:
            def get(self, day_iso, *, user_id=None):
                if day_iso == "2026-04-20":
                    return WorkRecord(
                        date="2026-04-20",
                        start="22:00",
                        end="09:00",
                        break_hours=1.0,
                        note="Night shift",
                        work_type="normal",
                        overnight=1,
                    )
                return None

        out = report_service.generate_weekly(
            selected=date(2026, 4, 20),
            db=_FakeDB(),
            work_hours=8.0,
            lang="en_US",
            user_id=1,
        )
        self.assertIn("Night", out)

    def test_i18n_fallback_for_overnight_labels(self):
        for lang in LANG_NAMES:
            tr = get_translator(lang)
            self.assertIsInstance(tr.gettext("Night"), str)
            self.assertIsInstance(tr.gettext("N"), str)


if __name__ == "__main__":
    unittest.main()

