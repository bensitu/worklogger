from __future__ import annotations
import csv
from datetime import datetime as dt, date

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTextEdit, QTabWidget, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QSplitter, QSizePolicy, QApplication,
)
from PySide6.QtCore import Qt, QTimer, QSize, QEvent
from PySide6.QtGui import QFont

from config.i18n import T
from config.themes import THEMES
from config.constants import WORK_TYPE_KEYS, LEAVE_TYPES
from core.time_calc import calc_hours
from services import analytics_service
from ui.widgets import BarChart
from .ai_dialogs import AIProgressDialog, AIResultDialog
from .template_dialogs import TemplatePickerDialog
from .common import (
    _append_quick_logs_block, _format_cal_events, _format_quick_logs, _get_ai_params, _localize_msgbox_buttons,
)


class NoteEditorDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        t = T[app_ref.lang]
        self.setWindowTitle(t["note_dlg_title"])
        self.setMinimumSize(600, 460)
        self.resize(700, 560)

        lv = QVBoxLayout(self)
        lv.setSpacing(8)

        d = app_ref.selected
        dow = T[app_ref.lang]["days"][(d.weekday() + 1) % 7]
        banner = QLabel(f"{d.year}/{d.month:02d}/{d.day:02d}  {dow}")
        banner.setObjectName("date_banner")
        banner.setAlignment(Qt.AlignCenter)
        lv.addWidget(banner)

        cal_events = app_ref.services.get_calendar_events_for_date(d.isoformat())
        if cal_events:
            cal_lbl = QLabel(t["cal_events_context"] + "  " +
                             " / ".join(e["summary"] for e in cal_events[:4]))
            cal_lbl.setObjectName("muted")
            cal_lbl.setWordWrap(True)
            lv.addWidget(cal_lbl)

        self._editor = QTextEdit()
        self._editor.setFont(QFont("monospace", 11))
        self._editor.setPlainText(app_ref.note_in.toPlainText())
        lv.addWidget(self._editor, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        tpl_btn = QPushButton(t["tpl_btn"])
        tpl_btn.clicked.connect(self._open_template_picker)
        toolbar.addWidget(tpl_btn)
        ql_btn = QPushButton(t.get("quick_log_insert_btn", "Insert Quick Log"))
        ql_btn.clicked.connect(self._insert_quick_logs)
        toolbar.addWidget(ql_btn)
        toolbar.addStretch()
        lv.addLayout(toolbar)

        self._hint = QLineEdit()
        self._hint.setPlaceholderText(t["ai_btn_hint"])
        lv.addWidget(self._hint)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        self._ai_btn = QPushButton(t["ai_btn"])
        self._copy_btn = QPushButton(t["report_copy"])
        apply_btn = QPushButton(t["note_apply"])
        apply_btn.setObjectName("primary_btn")
        cancel_btn = QPushButton(t["btn_close"])

        self._ai_btn.clicked.connect(self._ai_smart)
        self._copy_btn.clicked.connect(self._copy)
        apply_btn.clicked.connect(self._apply_and_close)
        cancel_btn.clicked.connect(self.reject)

        bot.addWidget(self._ai_btn)
        bot.addWidget(self._copy_btn)
        bot.addStretch()
        bot.addWidget(cancel_btn)
        bot.addWidget(apply_btn)
        lv.addLayout(bot)

    def _open_template_picker(self):
        dlg = TemplatePickerDialog(
            self._app, "daily",
            current_content=self._editor.toPlainText(),
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted and dlg.chosen_content:
            self._editor.setPlainText(dlg.chosen_content)

    def _insert_quick_logs(self):
        t = T[self._app.lang]
        logs = self._app.services.quick_logs_for_date(
            self._app.selected.isoformat())
        if not logs:
            QMessageBox.information(
                self, t["note_dlg_title"], t["quick_log_no_entries"]
            )
            return
        block = _append_quick_logs_block("", self._app, "daily")
        existing = self._editor.toPlainText().rstrip()
        joiner = "\n\n" if existing else ""
        self._editor.setPlainText(f"{existing}{joiner}{block}".strip())

    def _ai_smart(self):
        app = self._app
        t = T[app.lang]
        api_key, base_url, model = _get_ai_params(app, secondary=False)
        if not api_key:
            QMessageBox.warning(
                self, t["note_dlg_title"], t["report_ai_key_missing"])
            return

        d = app.selected
        rec = app.services.get_record(d.isoformat())
        h = calc_hours(rec.start, rec.end, rec.break_hours) if rec and rec.has_times else 0.0
        wt = rec.safe_work_type() if rec else "normal"
        existing = self._editor.toPlainText().strip()
        hint = self._hint.text().strip()
        cal_evs = app.services.get_calendar_events_for_date(d.isoformat())
        quick_logs = app.services.quick_logs_for_date(d.isoformat())
        cal_block = ""
        if cal_evs:
            cal_block += f"\nCalendar events:\n{_format_cal_events(cal_evs)}"
        if quick_logs:
            cal_block += f"\nQuick log entries:\n{_format_quick_logs(quick_logs, app.lang, 'daily')}"

        if existing:
            system = (
                "You are a professional editor. The user already has draft notes "
                "for their daily work log. Improve and expand them using the "
                "calendar events and work data provided. Keep the same language "
                "and format. Do not remove information already written."
                + (f" Extra: {hint}" if hint else "")
            )
            user_content = (
                f"Date: {d.isoformat()}, Hours: {h:.1f}h, Work type: {wt}"
                f"{cal_block}\n\nExisting notes:\n{existing}"
            )
        else:
            system = (
                "You are a professional writing a concise daily work log entry. "
                "Generate clear, factual bullet-point notes based on the provided "
                "work data and calendar events. Keep it under 200 words."
                + (f" Extra: {hint}" if hint else "")
            )
            user_content = (
                f"Date: {d.isoformat()}, Hours: {h:.1f}h, Work type: {wt}"
                f"{cal_block}"
                + (f"\nHint: {hint}" if hint else "")
            )

        msgs = [{"role": "user", "content": f"[System: {system}]\n\n{user_content}"}]

        def do_ai():
            def on_success(generated_text: str):
                def on_regenerate():
                    do_ai()
                result_dlg = AIResultDialog(
                    self, app.lang, existing, generated_text, on_regenerate
                )
                if result_dlg.exec() == QDialog.Accepted:
                    self._editor.setPlainText(
                        result_dlg.generated_edit.toPlainText())

            AIProgressDialog.run(
                self, app.lang, t["note_ai_btn"],
                api_key, base_url, model, msgs,
                on_success=on_success,
                services=app.services,
            )

        do_ai()

    def _copy(self):
        t = T[self._app.lang]
        QApplication.clipboard().setText(self._editor.toPlainText())
        self._copy_btn.setText(t["report_copied"])
        QTimer.singleShot(
            2000, lambda: self._copy_btn.setText(t["report_copy"]))

    def _apply_and_close(self):
        self._app.note_in.setPlainText(self._editor.toPlainText())
        self.accept()


class ReportDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        t = T[app_ref.lang]
        self.setWindowTitle(t["report_title"])
        self.setMinimumSize(700, 520)
        self.resize(780, 620)

        lv = QVBoxLayout(self)
        self._tabs = QTabWidget()

        self._week_edit = self._make_editor()
        self._month_edit = self._make_editor()

        for editor, key in [(self._week_edit,  "report_weekly"),
                            (self._month_edit, "report_monthly")]:
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(6, 6, 6, 6)
            wl.addWidget(editor)
            self._tabs.addTab(w, t[key])

        lv.addWidget(self._tabs, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        tpl_btn = QPushButton(t["tpl_btn"])
        tpl_btn.clicked.connect(self._open_template_picker)
        toolbar.addWidget(tpl_btn)
        toolbar.addStretch()
        lv.addLayout(toolbar)

        self._hint = QLineEdit()
        self._hint.setPlaceholderText(t["ai_btn_hint"])
        lv.addWidget(self._hint)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        self._ai_btn = QPushButton(t["ai_btn"])
        self._cp_btn = QPushButton(t["report_copy"])
        self._dl_btn = QPushButton(t["report_download"])
        close_btn = QPushButton(t["btn_close"])
        close_btn.setObjectName("primary_btn")

        self._ai_btn.clicked.connect(self._ai_smart)
        self._cp_btn.clicked.connect(self._copy)
        self._dl_btn.clicked.connect(self._download)
        close_btn.clicked.connect(self.accept)

        bot.addWidget(self._ai_btn)
        bot.addSpacing(8)
        bot.addWidget(self._cp_btn)
        bot.addWidget(self._dl_btn)
        bot.addStretch()
        bot.addWidget(close_btn)
        lv.addLayout(bot)

        self._fill()

    def _make_editor(self) -> QTextEdit:
        e = QTextEdit()
        e.setFont(QFont("monospace", 11))
        return e

    def _current_editor(self) -> QTextEdit:
        return (self._week_edit if self._tabs.currentIndex() == 0
                else self._month_edit)

    def _current_type(self) -> str:
        return "weekly" if self._tabs.currentIndex() == 0 else "monthly"

    def _fill(self):
        app = self._app
        self._week_edit.setPlainText(
            app.services.generate_weekly_report(
                app.selected, app.work_hours, app.lang))
        self._month_edit.setPlainText(
            app.services.generate_monthly_report(
                app.current.year, app.current.month,
                app.work_hours, app.lang))

    def _open_template_picker(self):
        dlg = TemplatePickerDialog(
            self._app, self._current_type(),
            current_content=self._current_editor().toPlainText(),
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted and dlg.chosen_content:
            self._current_editor().setPlainText(dlg.chosen_content)

    def _ai_smart(self):
        app = self._app
        t = T[app.lang]
        api_key, base_url, model = _get_ai_params(app, secondary=True)
        if not api_key:
            QMessageBox.warning(self, t["report_title"],
                                t["report_ai_key_missing"])
            return

        import datetime as _dt
        idx = self._tabs.currentIndex()
        existing = self._current_editor().toPlainText().strip()
        hint = self._hint.text().strip()
        period = t["report_weekly"] if idx == 0 else t["report_monthly"]

        if idx == 0:
            monday = app.selected - _dt.timedelta(days=app.selected.weekday())
            sunday = monday + _dt.timedelta(days=6)
            cal_evs = app.services.get_calendar_events_for_range(
                monday.isoformat(), sunday.isoformat())
            quick_logs = app.services.quick_logs_for_range(
                monday.isoformat(), sunday.isoformat())
        else:
            y, m = app.current.year, app.current.month
            from calendar import monthrange
            _, last = monthrange(y, m)
            cal_evs = app.services.get_calendar_events_for_range(
                f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}")
            quick_logs = app.services.quick_logs_for_range(
                f"{y}-{m:02d}-01", f"{y}-{m:02d}-{last:02d}")

        cal_block = ""
        if cal_evs:
            cal_block += f"\n\n=== Calendar Events ===\n{_format_cal_events(cal_evs)}"
        if quick_logs:
            cal_block += (
                f"\n\n=== Quick Log Entries (recorded tasks) ===\n"
                f"{_format_quick_logs(quick_logs, app.lang, 'summary')}"
            )

        if existing:
            system = (
                f"You are a professional work-report editor. "
                f"The user has a draft {period}. "
                f"Improve its clarity, structure, and completeness. "
                f"If calendar events are provided, incorporate any missing "
                f"meetings or tasks. Keep the same language and Markdown format. "
                f"Do not invent facts."
                + (f" Extra: {hint}" if hint else "")
            )
            user_content = f"=== Draft Report ===\n{existing}{cal_block}"
        else:
            system = (
                f"You are a professional work-report writer. "
                f"Generate a clean {period} using the raw work log data"
                + (" and calendar events provided" if cal_evs else "")
                + ". Write in the same language as the work log data. "
                f"Use Markdown. Do not invent facts."
                + (f" Extra: {hint}" if hint else "")
            )
            if idx == 0:
                raw_log = app.services.generate_weekly_report(
                    app.selected, app.work_hours, app.lang)
            else:
                raw_log = app.services.generate_monthly_report(
                    app.current.year, app.current.month,
                    app.work_hours, app.lang)
            user_content = f"=== Work Log ===\n{raw_log}{cal_block}"

        msgs = [{"role": "user",
                 "content": f"[System: {system}]\n\n{user_content}"}]

        def do_ai():
            existing = self._current_editor().toPlainText().strip()

            def on_success(generated_text: str):
                def on_regenerate():
                    do_ai()
                result_dlg = AIResultDialog(
                    self, app.lang, existing, generated_text, on_regenerate
                )
                if result_dlg.exec() == QDialog.Accepted:
                    self._current_editor().setPlainText(result_dlg.generated_edit.toPlainText())

            AIProgressDialog.run(
                self, app.lang, t["report_ai_gen"],
                api_key, base_url, model, msgs,
                on_success=on_success,
                services=app.services,
            )

        do_ai()

    def _copy(self):
        t = T[self._app.lang]
        QApplication.clipboard().setText(self._current_editor().toPlainText())
        self._cp_btn.setText(t["report_copied"])
        QTimer.singleShot(2000, lambda: self._cp_btn.setText(t["report_copy"]))

    def _download(self):
        app = self._app
        t = T[app.lang]
        idx = self._tabs.currentIndex()
        ts = dt.now().strftime("%Y%m%d_%H%M%S")
        label = "weekly" if idx == 0 else "monthly"
        defn = f"report_{label}_{ts}.md"
        path, _ = QFileDialog.getSaveFileName(
            self, t["report_download"], defn, "Markdown (*.md)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._current_editor().toPlainText())
        QMessageBox.information(
            self, t["btn_ok"], t["export_saved"].format(path))


class ChartDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        t = T[app_ref.lang]
        self.setWindowTitle(t["chart_title"])
        self.setMinimumSize(560, 440)
        self.resize(640, 520)

        lv = QVBoxLayout(self)
        acc = THEMES[app_ref.theme][app_ref.dark][0]
        mt = app_ref._safe_float_setting("monthly_target",
                                         app_ref.work_hours * 21)

        self._tabs_w = QTabWidget()
        self._charts: list[BarChart] = []
        self._datas:  list[list] = []

        specs = [
            (t["tab_monthly"],   self._monthly_data(),   mt / 4.3),
            (t["tab_quarterly"], self._quarterly_data(), mt * 3),
            (t["tab_annual"],    self._annual_data(),    mt),
        ]
        for name, data, ref in specs:
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(8, 8, 8, 8)
            chart = BarChart(data, ref=ref, dark=app_ref.dark,
                             accent=acc, unit=t["h_unit"],
                             no_data=t["no_data"])
            wl.addWidget(chart)
            self._tabs_w.addTab(w, name)
            self._charts.append(chart)
            self._datas.append(data)

        lv.addWidget(self._tabs_w, 1)

        bot = QHBoxLayout()
        bot.setSpacing(8)
        csv_btn = QPushButton("⬇  CSV")
        pdf_btn = QPushButton("⬇  PDF")
        close_btn = QPushButton(t["btn_close"])
        close_btn.setObjectName("primary_btn")
        csv_btn.clicked.connect(self._export_csv)
        pdf_btn.clicked.connect(self._export_pdf)
        close_btn.clicked.connect(self.accept)
        bot.addWidget(csv_btn)
        bot.addWidget(pdf_btn)
        bot.addStretch()
        bot.addWidget(close_btn)
        lv.addLayout(bot)

    def _month_stats(self, y, m):
        app = self._app
        rows = app.services.month_records(f"{y}-{m:02d}")
        return analytics_service.month_stats(rows, app.work_hours)

    def _monthly_data(self):
        app = self._app
        y, m = app.current.year, app.current.month
        return analytics_service.monthly_chart_data(app.services.get_record, y, m)

    def _quarterly_data(self):
        app = self._app
        y = app.current.year
        return analytics_service.quarter_hours(app.services.month_records, y)

    def _annual_data(self):
        app = self._app
        t = T[app.lang]
        y = app.current.year
        return analytics_service.annual_hours(app.services.month_records, y, t["month_short"])

    def _monthly_detail(self):
        app = self._app
        t = T[app.lang]
        y, m = app.current.year, app.current.month
        rows = []
        wk_map = {"normal": "wt_normal", "remote": "wt_remote",
                  "business_trip": "wt_business", "paid_leave": "wt_paid",
                  "comp_leave": "wt_comp", "sick_leave": "wt_sick"}
        for rec in sorted(app.services.month_records(f"{y}-{m:02d}"),
                          key=lambda r: r.date):
            h = calc_hours(rec.start, rec.end, rec.break_hours) if rec.has_times else 0.0
            ot = max(h - app.work_hours, 0)
            wt = rec.safe_work_type()
            rows.append({"date": rec.date,
                         "start": rec.start or "—",
                         "end": rec.end or "—",
                         "h": h, "ot": ot,
                         "wt": t.get(wk_map.get(wt, "wt_normal"), wt),
                         "note": rec.safe_note()})
        return rows

    def _quarterly_detail(self):
        app = self._app
        y = app.current.year
        rows = []
        for q in range(1, 5):
            tot = ot = wd = ld = 0.0
            for m in range((q-1)*3+1, q*3+1):
                a, b, c, d, _ = self._month_stats(y, m)
                tot += a
                ot += b
                wd += c
                ld += d
            rows.append({"q": f"Q{q}", "total": tot, "ot": ot,
                         "wd": int(wd), "ld": int(ld),
                         "avg": tot/wd if wd else 0.0})
        return rows

    def _annual_detail(self):
        app = self._app
        t = T[app.lang]
        y = app.current.year
        rows = []
        for m in range(1, 13):
            total, ot, wd, ld, avg = self._month_stats(y, m)
            rows.append({"m": t["month_short"][m-1], "total": total,
                         "ot": ot, "wd": wd, "ld": ld, "avg": avg})
        return rows

    def _current(self):
        i = self._tabs_w.currentIndex()
        return self._datas[i], self._charts[i]

    def _default_pdf_name(self):
        app = self._app
        y, m = app.current.year, app.current.month
        ts = dt.now().strftime("%Y%m%d_%H%M%S")
        idx = self._tabs_w.currentIndex()
        sfx = [f"monthly_{y}{m:02d}", f"quarterly_{y}", f"annual_{y}"][idx]
        return f"worklog_{sfx}_{ts}.pdf"

    def _export_csv(self):
        data, _ = self._current()
        app = self._app
        t = T[app.lang]
        ts = dt.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, t["export_title"] + " CSV", f"chart_{ts}.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["period", f"hours ({t['h_unit']})"])
            w.writerows(data)
        QMessageBox.information(self, "Export", t["export_saved"].format(path))

    def _export_pdf(self):
        data, chart_widget = self._current()
        app = self._app
        t = T[app.lang]
        try:
            from PySide6.QtPrintSupport import QPrinter
        except ImportError:
            QMessageBox.warning(self, t["export_title"],
                                t["pdf_requires_print_support"])
            path, _ = QFileDialog.getSaveFileName(
                self, "PNG", "chart.png", "PNG(*.png)")
            if path:
                chart_widget.grab().save(path)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, t["export_title"] + " PDF", self._default_pdf_name(), "PDF (*.pdf)")
        if not path:
            return
        idx = self._tabs_w.currentIndex()
        tab = self._tabs_w.tabText(idx)
        detail_fns = [self._pdf_monthly, self._pdf_quarterly, self._pdf_annual]
        from services.export_service import render_pdf, PdfContext
        ctx = PdfContext(
            lang=app.lang,
            theme=app.theme,
            dark=app.dark,
            year=app.current.year,
            month=app.current.month,
            work_hours=app.work_hours,
            monthly_target=app._safe_float_setting(
                "monthly_target", app.work_hours * 21),
        )
        try:
            render_pdf(path, idx, tab, chart_widget, data, detail_fns[idx], ctx)
            QMessageBox.information(
                self, t["export_title"], t["export_saved"].format(path))
        except Exception as exc:
            QMessageBox.critical(self, t["export_title"], str(exc))

    def _pdf_monthly(self, p, pw, ph, pt, t, top, ctx):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QBrush, QFont
        from PySide6.QtCore import Qt
        rows = self._monthly_detail()
        if not rows:
            return
        total, ot, wd, ld, avg = self._month_stats(
            ctx.year, ctx.month)
        cols = [(t["stat_total"], f"{total:.1f}{t['h_unit']}"),
                (t["stat_ot"],    f"{ot:.1f}{t['h_unit']}"),
                (t["stat_avg"],   f"{avg:.1f}{t['h_unit']}"),
                (t["stat_days"],  f"{int(wd)}{t['d_unit']}"),
                (t["stat_leave"], f"{int(ld)}{t['d_unit']}")]
        box_h = pt(34)
        cw2 = pw / len(cols)
        p.setBrush(QBrush(QColor("#f0f4ff")))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, top, pw, box_h), pt(6), pt(6))
        for i, (k, v) in enumerate(cols):
            cx = i * cw2
            fk = QFont("sans-serif")
            fk.setPixelSize(pt(8))
            p.setFont(fk)
            p.setPen(QColor("#606888"))
            p.drawText(QRectF(cx, top+pt(4), cw2, pt(12)), Qt.AlignCenter, k)
            fv = QFont("sans-serif")
            fv.setPixelSize(pt(11))
            fv.setBold(True)
            p.setFont(fv)
            p.setPen(QColor("#1e2035"))
            p.drawText(QRectF(cx, top+pt(16), cw2, pt(14)), Qt.AlignCenter, v)
        top += box_h + pt(6)
        hdrs = [("Date", 0.13), (t["start"], 0.10), (t["end"], 0.10),
                (t["h_unit"], 0.09), ("OT", 0.09), (t["wt_label"], 0.16), (t["note"], 0.33)]
        rh = pt(16)
        p.setBrush(QBrush(QColor("#dde6f8")))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, top, pw, rh))
        fh = QFont("sans-serif")
        fh.setPixelSize(pt(8))
        fh.setBold(True)
        p.setFont(fh)
        p.setPen(QColor("#1e2035"))
        x = 0
        for lbl, frac in hdrs:
            cw = pw*frac
            p.drawText(QRectF(x+pt(2), top, cw-pt(4), rh),
                       Qt.AlignVCenter | Qt.AlignLeft, lbl)
            x += cw
        top += rh
        fr = QFont("sans-serif")
        fr.setPixelSize(pt(7))
        for i, row in enumerate(rows):
            bg = QColor("#f7f9ff") if i % 2 == 0 else QColor("#ffffff")
            p.setBrush(QBrush(bg))
            p.setPen(Qt.NoPen)
            rh2 = pt(13)
            p.drawRect(QRectF(0, top, pw, rh2))
            p.setFont(fr)
            p.setPen(QColor("#1e2035"))
            vals = [row["date"], row["start"], row["end"],
                    f"{row['h']:.1f}" if row["h"] else "—",
                    f"+{row['ot']:.1f}" if row["ot"] > 0 else "—",
                    row["wt"], row["note"][:30]]
            x = 0
            for val, (_, frac) in zip(vals, hdrs):
                cw = pw*frac
                p.drawText(QRectF(x+pt(2), top, cw-pt(4), rh2),
                           Qt.AlignVCenter | Qt.AlignLeft, str(val))
                x += cw
            top += rh2
            if top > ph - pt(24):
                fi = QFont("sans-serif")
                fi.setPixelSize(pt(8))
                p.setFont(fi)
                p.setPen(QColor("#9090a8"))
                p.drawText(QRectF(0, top+pt(4), pw, pt(12)), Qt.AlignCenter,
                           f"… {len(rows)-i-1} more rows")
                break

    def _pdf_quarterly(self, p, pw, ph, pt, t, top, ctx):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QBrush, QFont
        from PySide6.QtCore import Qt
        rows = self._quarterly_detail()
        hdrs = [("Quarter", 0.15), (t["stat_total"], 0.17), (t["stat_ot"], 0.17),
                (t["stat_avg"], 0.17), (t["stat_days"], 0.17), (t["stat_leave"], 0.17)]
        rh = pt(16)
        p.setBrush(QBrush(QColor("#dde6f8")))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, top, pw, rh))
        fh = QFont("sans-serif")
        fh.setPixelSize(pt(8))
        fh.setBold(True)
        p.setFont(fh)
        p.setPen(QColor("#1e2035"))
        x = 0
        for lbl, frac in hdrs:
            cw = pw*frac
            p.drawText(QRectF(x+pt(2), top, cw-pt(4), rh),
                       Qt.AlignVCenter | Qt.AlignLeft, lbl)
            x += cw
        top += rh
        fr = QFont("sans-serif")
        fr.setPixelSize(pt(9))
        for i, row in enumerate(rows):
            bg = QColor("#f7f9ff") if i % 2 == 0 else QColor("#ffffff")
            p.setBrush(QBrush(bg))
            p.setPen(Qt.NoPen)
            rh2 = pt(20)
            p.drawRect(QRectF(0, top, pw, rh2))
            p.setFont(fr)
            p.setPen(QColor("#1e2035"))
            vals = [row["q"], f"{row['total']:.1f}{t['h_unit']}",
                    f"{row['ot']:.1f}{t['h_unit']}", f"{row['avg']:.1f}{t['h_unit']}",
                    f"{row['wd']}{t['d_unit']}", f"{row['ld']}{t['d_unit']}"]
            x = 0
            for val, (_, frac) in zip(vals, hdrs):
                cw = pw*frac
                p.drawText(QRectF(x+pt(3), top, cw-pt(6), rh2),
                           Qt.AlignVCenter | Qt.AlignLeft, str(val))
                x += cw
            top += rh2

    def _pdf_annual(self, p, pw, ph, pt, t, top, ctx):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QBrush, QFont
        from PySide6.QtCore import Qt
        s = [self._month_stats(ctx.year, m) for m in range(1, 13)]
        total = sum(x[0] for x in s)
        ot = sum(x[1] for x in s)
        wd = sum(x[2] for x in s)
        ld = sum(x[3] for x in s)
        avg = total/wd if wd else 0.0
        cols = [(t["stat_total"], f"{total:.1f}{t['h_unit']}"), (t["stat_ot"], f"{ot:.1f}{t['h_unit']}"),
                (t["stat_avg"], f"{avg:.1f}{t['h_unit']}"), (
                    t["stat_days"], f"{int(wd)}{t['d_unit']}"),
                (t["stat_leave"], f"{int(ld)}{t['d_unit']}")]
        box_h = pt(34)
        cw2 = pw/len(cols)
        p.setBrush(QBrush(QColor("#f0f4ff")))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, top, pw, box_h), pt(6), pt(6))
        for i, (k, v) in enumerate(cols):
            cx = i*cw2
            fk = QFont("sans-serif")
            fk.setPixelSize(pt(8))
            p.setFont(fk)
            p.setPen(QColor("#606888"))
            p.drawText(QRectF(cx, top+pt(4), cw2, pt(12)), Qt.AlignCenter, k)
            fv = QFont("sans-serif")
            fv.setPixelSize(pt(11))
            fv.setBold(True)
            p.setFont(fv)
            p.setPen(QColor("#1e2035"))
            p.drawText(QRectF(cx, top+pt(16), cw2, pt(14)), Qt.AlignCenter, v)
        top += box_h+pt(6)
        rows = self._annual_detail()
        hdrs = [("Month", 0.12), (t["stat_total"], 0.17), (t["stat_ot"], 0.17),
                (t["stat_avg"], 0.17), (t["stat_days"], 0.17), (t["stat_leave"], 0.20)]
        rh = pt(16)
        p.setBrush(QBrush(QColor("#dde6f8")))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, top, pw, rh))
        fh = QFont("sans-serif")
        fh.setPixelSize(pt(8))
        fh.setBold(True)
        p.setFont(fh)
        p.setPen(QColor("#1e2035"))
        x = 0
        for lbl, frac in hdrs:
            cw = pw*frac
            p.drawText(QRectF(x+pt(2), top, cw-pt(4), rh),
                       Qt.AlignVCenter | Qt.AlignLeft, lbl)
            x += cw
        top += rh
        fr = QFont("sans-serif")
        fr.setPixelSize(pt(8))
        for i, row in enumerate(rows):
            bg = QColor("#f7f9ff") if i % 2 == 0 else QColor("#ffffff")
            p.setBrush(QBrush(bg))
            p.setPen(Qt.NoPen)
            rh2 = pt(17)
            p.drawRect(QRectF(0, top, pw, rh2))
            p.setFont(fr)
            p.setPen(QColor("#1e2035" if row["total"] > 0 else "#9090a8"))
            vals = [row["m"], f"{row['total']:.1f}{t['h_unit']}", f"{row['ot']:.1f}{t['h_unit']}",
                    f"{row['avg']:.1f}{t['h_unit']}", f"{row['wd']}{t['d_unit']}", f"{row['ld']}{t['d_unit']}"]
            x = 0
            for val, (_, frac) in zip(vals, hdrs):
                cw = pw*frac
                p.drawText(QRectF(x+pt(3), top, cw-pt(6), rh2),
                           Qt.AlignVCenter | Qt.AlignLeft, str(val))
                x += cw
            top += rh2


class QuickLogDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        t = T[app_ref.lang]
        self.setWindowTitle(t["quick_log_title"])
        self.setMinimumSize(500, 400)
        self.resize(640, 440)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        from datetime import datetime as _dt
        from core.validator import parse_time as _parse_time
        self._parse_time = _parse_time
        self._editing_id: int | None = None
        self._row_widgets: dict[int, tuple[QWidget, QLabel, QPushButton]] = {}
        self._hovered_row_id: int | None = None

        outer = QVBoxLayout(self)
        outer.setSpacing(6)
        outer.setContentsMargins(10, 8, 10, 8)

        d = app_ref.selected
        dow = T[app_ref.lang]["days"][(d.weekday() + 1) % 7]
        banner = QLabel(f"{d.year}/{d.month:02d}/{d.day:02d}  {dow}")
        banner.setObjectName("date_banner")
        banner.setAlignment(Qt.AlignCenter)
        outer.addWidget(banner)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setContentsMargins(5, 5, 5, 5)
        splitter.setChildrenCollapsible(False)

        left_w = QWidget()
        lft = QVBoxLayout(left_w)
        lft.setContentsMargins(3, 0, 3, 0)
        lft.setSpacing(4)

        lbl = QLabel(t["quick_log_today"])
        lbl.setObjectName("muted")
        lft.addWidget(lbl)

        self._list = QListWidget()
        self._list.setObjectName("quick_log_list")
        self._list.setAlternatingRowColors(False)
        self._list.setSpacing(0)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setStyleSheet(
            "QListWidget#quick_log_list::item{padding:2px 4px; margin:0px; border:none;}"
            "QListWidget#quick_log_list::item:selected{background:transparent; border:none;}"
            "QListWidget#quick_log_list::item:hover{background:transparent;}"
        )
        self._list.itemClicked.connect(self._load_for_edit)
        self._list.currentItemChanged.connect(self._on_list_current_changed)
        lft.addWidget(self._list, 1)

        right_w = QWidget()
        rgt = QVBoxLayout(right_w)
        rgt.setContentsMargins(4, 0, 0, 0)
        rgt.setSpacing(8)

        time_lbl = QLabel(t["quick_log_time"])
        time_lbl.setObjectName("muted")
        rgt.addWidget(time_lbl)

        now_str = _dt.now().strftime("%H:%M")

        time_row = QHBoxLayout()
        time_row.setSpacing(4)
        self._clk_start_btn = QPushButton(t["clock"])
        self._clk_start_btn.setObjectName("clock_btn")
        self._clk_start_btn.setFixedWidth(50)
        self._clk_start_btn.clicked.connect(
            lambda: self._time_in.setText(_dt.now().strftime("%H:%M")))

        self._time_in = QLineEdit(now_str)
        self._time_in.setPlaceholderText("9  /  930  /  09:30")
        self._time_in.setFixedWidth(85)
        self._time_in.editingFinished.connect(
            lambda: self._normalise_time(self._time_in))

        arrow = QLabel(" → ")
        arrow.setAlignment(Qt.AlignCenter)

        self._end_in = QLineEdit()
        self._end_in.setPlaceholderText(t["quick_log_end_time"])
        self._end_in.setFixedWidth(85)
        self._end_in.editingFinished.connect(
            lambda: self._normalise_time(self._end_in))

        self._clk_end_btn = QPushButton(t["clock"])
        self._clk_end_btn.setObjectName("clock_btn")
        self._clk_end_btn.setFixedWidth(50)
        self._clk_end_btn.clicked.connect(
            lambda: self._end_in.setText(_dt.now().strftime("%H:%M")))

        time_row.addWidget(self._clk_start_btn)
        time_row.addWidget(self._time_in)
        time_row.addWidget(arrow)
        time_row.addWidget(self._end_in)
        time_row.addWidget(self._clk_end_btn)
        time_row.addStretch()
        rgt.addLayout(time_row)

        desc_lbl = QLabel(t["quick_log_desc"])
        desc_lbl.setObjectName("muted")
        rgt.addWidget(desc_lbl)

        self._desc_in = QLineEdit()
        self._desc_in.setPlaceholderText(t["quick_log_desc"])
        self._desc_in.returnPressed.connect(self._add_entry)
        rgt.addWidget(self._desc_in)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._add_btn = QPushButton(t["quick_log_add"])
        self._add_btn.setObjectName("primary_btn")
        self._add_btn.clicked.connect(self._add_entry)
        self._cancel_edit_btn = QPushButton(t["btn_close"])
        self._cancel_edit_btn.setVisible(False)
        self._cancel_edit_btn.clicked.connect(self._cancel_edit)
        btn_row.addStretch()
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._cancel_edit_btn)
        rgt.addLayout(btn_row)

        rgt.addStretch()

        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 4)
        outer.addWidget(splitter, 1)

        bot = QHBoxLayout()
        hint_lbl = QLabel(t["quick_log_hint"])
        hint_lbl.setObjectName("muted")
        hint_lbl.setWordWrap(True)
        close_btn = QPushButton(t["btn_close"])
        close_btn.clicked.connect(self.accept)
        bot.addWidget(hint_lbl, 1)
        bot.addWidget(close_btn)
        outer.addLayout(bot)

        self._refresh_list()
        self._desc_in.setFocus()

    def _normalise_time(self, field: QLineEdit):
        raw = field.text().strip()
        if not raw:
            field.setStyleSheet("")
            return
        parsed = self._parse_time(raw)
        if parsed:
            field.setText(parsed)
            field.setStyleSheet("")
        else:
            field.setStyleSheet("QLineEdit{border:2px solid #e03333;}")

    def _refresh_list(self):
        d_str = self._app.selected.isoformat()
        self._row_widgets.clear()
        self._list.setUpdatesEnabled(False)
        self._list.clear()
        entries = self._app.services.quick_logs_for_date(d_str)
        t = T[self._app.lang]
        hover_color = THEMES[self._app.theme][self._app.dark][1]
        if not entries:
            placeholder = QListWidgetItem(t["quick_log_no_entries"])
            placeholder.setFlags(Qt.NoItemFlags)
            self._list.addItem(placeholder)
        else:
            for entry in entries:
                t_str = entry["time"]
                if entry.get("end_time"):
                    t_str += f"–{entry['end_time']}"
                full_text = f"{t_str}  {entry['description']}"
                item = QListWidgetItem()
                item.setSizeHint(QSize(0, 30))
                item.setData(Qt.UserRole, entry)
                row_w = QWidget()
                row_w.setObjectName("quick_log_row")
                row_l = QHBoxLayout(row_w)
                row_l.setContentsMargins(5, 0, 4, 0)
                row_l.setSpacing(4)
                text_lbl = QLabel(full_text)
                text_lbl.setSizePolicy(
                    QSizePolicy.Expanding, QSizePolicy.Preferred)
                text_lbl.setCursor(Qt.PointingHandCursor)
                text_lbl.setToolTip(full_text)
                text_lbl.setStyleSheet(
                    f"QLabel:hover{{color:{hover_color};}}"
                )
                text_lbl.mousePressEvent = lambda e, it=item, ent=entry: self._activate_row(
                    it, ent)
                row_l.addWidget(text_lbl, 1)
                x_btn = QPushButton("✕")
                x_btn.setStyleSheet(
                    "QPushButton{color:#e03333; font-weight:bold; border:none; "
                    "margin:0px; padding:0px; background:transparent;}"
                    "QPushButton:hover{color:#ff0000; background:transparent;}"
                )
                x_btn.setFixedSize(18, 18)
                x_btn.setToolTip(t["quick_log_delete"])
                x_btn.setCursor(Qt.PointingHandCursor)
                x_btn.setVisible(False)
                x_btn.clicked.connect(
                    lambda checked, lid=entry["id"]: self._delete_one(lid))
                row_l.addWidget(x_btn)
                for obj in (row_w, text_lbl, x_btn):
                    obj.setProperty("quick_log_id", entry["id"])
                    obj.installEventFilter(self)
                row_w.mousePressEvent = lambda e, it=item, ent=entry: self._activate_row(
                    it, ent)
                self._list.addItem(item)
                self._list.setItemWidget(item, row_w)
                self._row_widgets[entry["id"]] = (row_w, text_lbl, x_btn)
        self._sync_row_styles()
        self._list.setUpdatesEnabled(True)

    def _load_for_edit(self, item):
        if item is None:
            return
        entry = item.data(Qt.UserRole)
        if not entry:
            return
        self._do_load(entry)

    def _activate_row(self, item, entry):
        self._list.setCurrentItem(item)
        self._do_load(entry)

    def _on_list_current_changed(self, _current, _previous):
        self._sync_row_styles()

    def _sync_row_styles(self):
        acc = THEMES[self._app.theme][self._app.dark][0]
        acc_dim = THEMES[self._app.theme][self._app.dark][2]
        hov = THEMES[self._app.theme][self._app.dark][3]
        txt = "#c8cde8" if self._app.dark else "#1e2035"
        selected = self._list.currentItem()
        for i in range(self._list.count()):
            item = self._list.item(i)
            entry = item.data(Qt.UserRole)
            if not entry:
                continue
            refs = self._row_widgets.get(entry["id"])
            if not refs:
                continue
            row_w, text_lbl, _x_btn = refs
            is_selected = item is selected
            is_hovered = entry["id"] == self._hovered_row_id
            if is_selected:
                row_w.setStyleSheet(
                    f"QWidget#quick_log_row{{background:{acc_dim};"
                    f"border:1px solid {acc};border-radius:6px;}}"
                )
                text_lbl.setStyleSheet(f"QLabel{{color:{txt};}}")
            elif is_hovered:
                row_w.setStyleSheet(
                    f"QWidget#quick_log_row{{background:{hov};border:1px solid transparent;"
                    "border-radius:6px;}"
                )
                text_lbl.setStyleSheet("")
            else:
                row_w.setStyleSheet(
                    "QWidget#quick_log_row{background:transparent;border:1px solid transparent;"
                    "border-radius:6px;}"
                )
                text_lbl.setStyleSheet("")

    def eventFilter(self, obj, event):
        entry_id = obj.property("quick_log_id")
        if entry_id is not None:
            if event.type() == QEvent.Enter:
                self._hovered_row_id = entry_id
                self._set_delete_visible(entry_id, True)
                self._sync_row_styles()
            elif event.type() == QEvent.Leave:
                QTimer.singleShot(
                    0, lambda eid=entry_id: self._refresh_hover_state(eid))
        return super().eventFilter(obj, event)

    def _set_delete_visible(self, entry_id: int, visible: bool):
        refs = self._row_widgets.get(entry_id)
        if refs:
            refs[2].setVisible(visible)

    def _refresh_hover_state(self, entry_id: int):
        refs = self._row_widgets.get(entry_id)
        if not refs:
            return
        hovered = any(w.underMouse() for w in refs)
        if not hovered and self._hovered_row_id == entry_id:
            self._hovered_row_id = None
        self._set_delete_visible(entry_id, hovered)
        self._sync_row_styles()

    def _do_load(self, entry):
        t = T[self._app.lang]
        self._editing_id = entry["id"]
        self._time_in.setText(entry["time"])
        self._end_in.setText(entry.get("end_time", "") or "")
        self._desc_in.setText(entry["description"])
        self._desc_in.setFocus()
        self._add_btn.setText(t["tpl_save"])
        self._cancel_edit_btn.setVisible(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) and item.data(Qt.UserRole)["id"] == entry["id"]:
                self._list.setCurrentRow(i)
                break

    def _cancel_edit(self):
        t = T[self._app.lang]
        self._editing_id = None
        from datetime import datetime as _dt
        self._time_in.setText(_dt.now().strftime("%H:%M"))
        self._end_in.clear()
        self._desc_in.clear()
        self._add_btn.setText(t["quick_log_add"])
        self._cancel_edit_btn.setVisible(False)
        self._list.clearSelection()
        self._sync_row_styles()

    def _add_entry(self):
        t = T[self._app.lang]
        desc = self._desc_in.text().strip()
        if not desc:
            self._desc_in.setFocus()
            self._desc_in.setStyleSheet("QLineEdit{border:2px solid #e03333;}")
            QTimer.singleShot(1500,
                              lambda: self._desc_in.setStyleSheet(""))
            return
        raw_start = self._time_in.text().strip()
        raw_end = self._end_in.text().strip()
        time_str = self._parse_time(raw_start) or raw_start or "00:00"
        end_str = self._parse_time(raw_end) or ""
        d_str = self._app.selected.isoformat()

        if self._editing_id is not None:
            self._app.services.update_quick_log(
                self._editing_id, desc, time_str, end_str)
        else:
            self._app.services.add_quick_log(d_str, time_str, desc, end_str)

        self._cancel_edit()
        self._refresh_list()

    def _delete_one(self, log_id: int):
        t = T[self._app.lang]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(t["quick_log_title"])
        box.setText(t["quick_log_delete_confirm"])
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _localize_msgbox_buttons(box, t)
        if box.exec() != QMessageBox.Yes:
            return
        self._app.services.delete_quick_log(log_id)
        if self._editing_id == log_id:
            self._cancel_edit()
        self._refresh_list()
