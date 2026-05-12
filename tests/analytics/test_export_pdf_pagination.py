import os
import re
import sys
import tempfile
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
APP_ROOT = os.path.join(PROJECT_ROOT, "worklogger")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from services.export_service import (
    PdfContext,
    PdfDetailSection,
    PdfMetric,
    pdf_colors,
    render_pdf,
)


def _pdf_page_count(path: str) -> int:
    with open(path, "rb") as handle:
        data = handle.read()
    return len(re.findall(rb"/Type\s*/Page\b", data))


class ExportPdfPaginationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._qt = QApplication.instance() or QApplication([])

    def test_dark_mode_pdf_uses_print_safe_light_colors(self):
        colors = pdf_colors(
            PdfContext(
                lang="en_US",
                theme="blue",
                dark=True,
                year=2026,
                month=4,
                work_hours=8.0,
                monthly_target=168.0,
            )
        )

        self.assertEqual(colors.page_bg, "#ffffff")
        self.assertEqual(colors.text, "#1e2035")

    def test_render_pdf_paginates_long_ai_narrative_and_detail_rows(self):
        pixmap = QPixmap(900, 260)
        pixmap.fill(QColor("#ffffff"))
        detail = PdfDetailSection(
            summary=[PdfMetric("Total", "240.0h")],
            headers=[
                ("Date", 0.18),
                ("Start", 0.12),
                ("End", 0.12),
                ("Hours", 0.12),
                ("Notes", 0.46),
            ],
            rows=[
                [
                    f"2026-04-{(idx % 30) + 1:02d}",
                    "09:00",
                    "18:00",
                    "8.0",
                    f"Detailed work note {idx} with enough text to require elision.",
                ]
                for idx in range(120)
            ],
        )
        narrative = "\n".join(
            f"- AI summary line {idx}: observed workload trend based on chart data."
            for idx in range(140)
        )
        ctx = PdfContext(
            lang="en_US",
            theme="blue",
            dark=True,
            year=2026,
            month=4,
            work_hours=8.0,
            monthly_target=168.0,
        )
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        render_pdf(
            path,
            0,
            "Monthly",
            pixmap,
            detail,
            ctx,
            ai_narrative=narrative,
        )

        self.assertGreater(_pdf_page_count(path), 1)


if __name__ == "__main__":
    unittest.main()

