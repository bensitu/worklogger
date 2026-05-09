import os
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.calendar_service import parse_ics_rich


class CalendarServiceTests(unittest.TestCase):
    def test_parse_ics_rich_skips_files_over_size_limit(self):
        fd, path = tempfile.mkstemp(suffix=".ics")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "wb") as handle:
            handle.write(b"BEGIN:VCALENDAR\n")

        with patch("services.calendar_service._ICS_MAX_BYTES", 8):
            self.assertEqual(parse_ics_rich(path), [])


if __name__ == "__main__":
    unittest.main()
