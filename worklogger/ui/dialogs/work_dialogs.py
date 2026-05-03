from __future__ import annotations
from calendar import monthrange
from datetime import datetime as dt, date, timedelta
from html import escape

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QLineEdit, QTextEdit, QTabWidget, QFileDialog, QMessageBox, QListWidget, QListWidgetItem,
    QSplitter, QSizePolicy, QApplication, QButtonGroup, QRadioButton,
)
from PySide6.QtCore import Qt, QTimer, QSize, QEvent
from PySide6.QtGui import QFont

from utils.i18n import _, msg
from config.themes import (
    ANALYTICS_LEAVE_LINE_COLOR,
    label_color_qss,
    line_edit_error_qss,
    quick_log_delete_button_qss,
    quick_log_label_hover_qss,
    quick_log_list_qss,
    quick_log_row_qss,
    quick_log_text_color,
    switch_off_color,
    theme_colors,
)
from config.constants import (
    ANALYTICS_SHOW_LEAVES_SETTING_KEY,
    MONTHLY_TARGET_SETTING_KEY,
)
from core.time_calc import calc_hours
from services import analytics_service
from services.export_service import pdf_colors
from ui.widgets import ComboChart, SwitchButton
from .ai_assist_launcher import AiAssistLaunchConfig, launch_ai_assist
from .template_dialogs import TemplatePickerDialog
from .common import (
    _append_quick_logs_block, _localize_msgbox_buttons,
)


class NoteEditorDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        self.setWindowTitle(_("Notes"))
        self.setMinimumSize(600, 460)
        self.resize(700, 560)

        lv = QVBoxLayout(self)
        lv.setSpacing(8)

        d = app_ref.selected
        dow = [_("Sun"), _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat")][(d.weekday() + 1) % 7]
        banner = QLabel(f"{d.year}/{d.month:02d}/{d.day:02d}  {dow}")
        banner.setObjectName("date_banner")
        banner.setAlignment(Qt.AlignCenter)
        lv.addWidget(banner)

        cal_events = app_ref.services.get_calendar_events_for_date(d.isoformat())
        if cal_events:
            cal_lbl = QLabel(_("Calendar events:") + "  " +
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
        tpl_btn = QPushButton(_("📋 Templates"))
        tpl_btn.clicked.connect(self._open_template_picker)
        toolbar.addWidget(tpl_btn)
        ql_btn = QPushButton(_("Insert Quick Log"))
        ql_btn.clicked.connect(self._insert_quick_logs)
        toolbar.addWidget(ql_btn)
        toolbar.addStretch()
        lv.addLayout(toolbar)

        self._hint = QLineEdit()
        self._hint.setPlaceholderText(_("Hint / extra instructions (optional)"))
        lv.addWidget(self._hint)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        self._ai_btn = QPushButton(msg("ai_btn"))
        self._copy_btn = QPushButton(msg("report_copy"))
        apply_btn = QPushButton(_("Apply"))
        apply_btn.setObjectName("primary_btn")
        cancel_btn = QPushButton(_("Close"))

        self._ai_btn.clicked.connect(self._ai_smart)
        self._copy_btn.clicked.connect(self._copy)
        apply_btn.clicked.connect(self._apply_and_close)
        cancel_btn.clicked.connect(self.reject)
        self._editor.textChanged.connect(self._sync_ai_button)
        self._hint.textChanged.connect(lambda _text: self._sync_ai_button())

        bot.addWidget(self._ai_btn)
        bot.addWidget(self._copy_btn)
        bot.addStretch()
        bot.addWidget(cancel_btn)
        bot.addWidget(apply_btn)
        lv.addLayout(bot)
        self._sync_ai_button()

    def _sync_ai_button(self) -> None:
        has_source = bool(self._editor.toPlainText().strip())
        has_hint = bool(self._hint.text().strip())
        self._ai_btn.setEnabled(has_source or has_hint)

    def _open_template_picker(self):
        dlg = TemplatePickerDialog(
            self._app, "daily",
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted and dlg.chosen_content:
            self._editor.setPlainText(dlg.chosen_content)

    def _insert_quick_logs(self):
        logs = self._app.services.quick_logs_for_date(
            self._app.selected.isoformat())
        if not logs:
            QMessageBox.information(
                self, _("Notes"), _("No entries yet today.")
            )
            return
        block = _append_quick_logs_block("", self._app, "daily")
        existing = self._editor.toPlainText().rstrip()
        joiner = "\n\n" if existing else ""
        self._editor.setPlainText(f"{existing}{joiner}{block}".strip())

    def _ai_smart(self):
        app = self._app
        d = app.selected
        launch_ai_assist(
            self,
            app,
            AiAssistLaunchConfig(
                period_type="daily",
                period_label=_("Daily Notes") + f" - {d.isoformat()}",
                existing_text=self._editor.toPlainText().strip(),
                hint=self._hint.text().strip(),
                apply_button_text=_("Apply to Notes"),
                use_secondary_ai=False,
            ),
            lambda text: self._editor.setPlainText(text),
        )

    def _copy(self):
        QApplication.clipboard().setText(self._editor.toPlainText())
        self._copy_btn.setText(msg("report_copied"))
        QTimer.singleShot(
            2000, lambda: self._copy_btn.setText(msg("report_copy")))

    def _apply_and_close(self):
        self._app.note_in.setPlainText(self._editor.toPlainText())
        self.accept()


class ReportDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        self.setWindowTitle(_("Work Report"))
        self.setMinimumSize(700, 520)
        self.resize(780, 620)

        lv = QVBoxLayout(self)
        self._tabs = QTabWidget()

        self._week_edit = self._make_editor()
        self._month_edit = self._make_editor()
        self._saved_text: dict[str, str] = {"weekly": "", "monthly": ""}

        for editor, key in [(self._week_edit,  "report_weekly"),
                            (self._month_edit, "report_monthly")]:
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(6, 6, 6, 6)
            wl.addWidget(editor)
            self._tabs.addTab(w, msg(key))

        lv.addWidget(self._tabs, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        tpl_btn = QPushButton(_("📋 Templates"))
        tpl_btn.clicked.connect(self._open_template_picker)
        toolbar.addWidget(tpl_btn)
        toolbar.addStretch()
        lv.addLayout(toolbar)

        self._hint = QLineEdit()
        self._hint.setPlaceholderText(_("Hint / extra instructions (optional)"))
        lv.addWidget(self._hint)

        bot = QHBoxLayout()
        bot.setSpacing(6)
        self._ai_btn = QPushButton(msg("ai_btn"))
        self._cp_btn = QPushButton(msg("report_copy"))
        self._dl_btn = QPushButton(msg("report_download"))
        self._save_btn = QPushButton(_("Save"))
        close_btn = QPushButton(_("Close"))
        close_btn.setObjectName("primary_btn")

        self._ai_btn.clicked.connect(self._ai_smart)
        self._cp_btn.clicked.connect(self._copy)
        self._dl_btn.clicked.connect(self._download)
        self._save_btn.clicked.connect(self._save_current_report)
        close_btn.clicked.connect(self._close_with_dirty_check)
        self._tabs.currentChanged.connect(lambda _idx: self._sync_ai_button())
        self._week_edit.textChanged.connect(self._sync_ai_button)
        self._month_edit.textChanged.connect(self._sync_ai_button)
        self._hint.textChanged.connect(lambda _text: self._sync_ai_button())

        bot.addWidget(self._ai_btn)
        bot.addSpacing(8)
        bot.addWidget(self._cp_btn)
        bot.addWidget(self._dl_btn)
        bot.addWidget(self._save_btn)
        bot.addStretch()
        bot.addWidget(close_btn)
        lv.addLayout(bot)

        self._fill()
        self._sync_ai_button()

    def _make_editor(self) -> QTextEdit:
        e = QTextEdit()
        e.setFont(QFont("monospace", 11))
        return e

    def _current_editor(self) -> QTextEdit:
        return (self._week_edit if self._tabs.currentIndex() == 0
                else self._month_edit)

    def _current_type(self) -> str:
        return "weekly" if self._tabs.currentIndex() == 0 else "monthly"

    def _sync_ai_button(self) -> None:
        has_source = bool(self._current_editor().toPlainText().strip())
        has_hint = bool(self._hint.text().strip())
        self._ai_btn.setEnabled(has_source or has_hint)

    def _period_for_type(self, report_type: str) -> tuple[str, str]:
        app = self._app
        if report_type == "weekly":
            monday = app.selected - timedelta(days=app.selected.weekday())
            sunday = monday + timedelta(days=6)
            return monday.isoformat(), sunday.isoformat()
        year, month = app.selected.year, app.selected.month
        _first_weekday, last_day = monthrange(year, month)
        return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"

    def _editor_for_type(self, report_type: str) -> QTextEdit:
        return self._week_edit if report_type == "weekly" else self._month_edit

    def _load_or_generate_report(self, report_type: str) -> str:
        app = self._app
        start, end = self._period_for_type(report_type)
        saved = app.services.get_report_for_period(report_type, start, end)
        if saved:
            return str(saved.get("content", ""))
        if report_type == "weekly":
            return app.services.generate_weekly_report(
                app.selected, app.work_hours, app.lang)
        return app.services.generate_monthly_report(
            app.selected.year, app.selected.month, app.work_hours, app.lang)

    def _dirty_report_types(self) -> list[str]:
        dirty = []
        for report_type in ("weekly", "monthly"):
            current_text = self._editor_for_type(report_type).toPlainText()
            if current_text != self._saved_text[report_type]:
                dirty.append(report_type)
        return dirty

    def _save_report_type(self, report_type: str, *, show_message: bool = False) -> bool:
        editor = self._editor_for_type(report_type)
        content = editor.toPlainText()
        try:
            start, end = self._period_for_type(report_type)
            self._app.services.save_report(
                report_type,
                start,
                end,
                content,
            )
        except ValueError as exc:
            text = (
                _("Report content is empty.")
                if str(exc) == "empty_report" else str(exc)
            )
            QMessageBox.warning(self, _("Work Report"), text)
            return False
        except Exception as exc:
            QMessageBox.critical(self, _("Work Report"), str(exc))
            return False
        self._saved_text[report_type] = content
        if show_message:
            QMessageBox.information(self, _("Work Report"), _("Report saved."))
        return True

    def _save_current_report(self):
        self._save_report_type(self._current_type(), show_message=True)

    def _confirm_save_dirty_reports(self) -> bool:
        dirty = self._dirty_report_types()
        if not dirty:
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Work Report"))
        box.setText(_("Reports have unsaved changes. Save before closing?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        _localize_msgbox_buttons(box, _)
        choice = box.exec()
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Discard:
            return True
        for report_type in dirty:
            if not self._save_report_type(report_type):
                return False
        return True

    def _close_with_dirty_check(self):
        if self._confirm_save_dirty_reports():
            self.accept()

    def reject(self):
        if self._confirm_save_dirty_reports():
            super().reject()

    def closeEvent(self, event):
        if self._confirm_save_dirty_reports():
            event.accept()
        else:
            event.ignore()

    def _fill(self):
        for report_type in ("weekly", "monthly"):
            text = self._load_or_generate_report(report_type)
            self._editor_for_type(report_type).setPlainText(text)
            self._saved_text[report_type] = text

    def _open_template_picker(self):
        dlg = TemplatePickerDialog(
            self._app, self._current_type(),
            parent=self,
        )
        if dlg.exec() == QDialog.Accepted and dlg.chosen_content:
            self._current_editor().setPlainText(dlg.chosen_content)

    def _ai_smart(self):
        app = self._app
        idx = self._tabs.currentIndex()
        period_type = "weekly" if idx == 0 else "monthly"
        period_label = _("Weekly Report") if idx == 0 else _("Monthly Report")
        launch_ai_assist(
            self,
            app,
            AiAssistLaunchConfig(
                period_type=period_type,
                period_label=period_label,
                existing_text=self._current_editor().toPlainText().strip(),
                hint=self._hint.text().strip(),
                apply_button_text=_("Apply to Report"),
                use_secondary_ai=True,
            ),
            lambda text: self._current_editor().setPlainText(text),
        )

    def _copy(self):
        QApplication.clipboard().setText(self._current_editor().toPlainText())
        self._cp_btn.setText(msg("report_copied"))
        QTimer.singleShot(2000, lambda: self._cp_btn.setText(msg("report_copy")))

    def _download(self):
        idx = self._tabs.currentIndex()
        ts = dt.now().strftime("%Y%m%d_%H%M%S")
        label = "weekly" if idx == 0 else "monthly"
        defn = f"report_{label}_{ts}.md"
        path, _dialog_filter = QFileDialog.getSaveFileName(
            self, msg("report_download"), defn, _("Markdown (*.md)"))
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._current_editor().toPlainText())
        QMessageBox.information(
            self, _("OK"), _("Saved: {}").format(path))


class ChartDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        self.setWindowTitle(_("Work Time Analytics"))
        self.setMinimumSize(560, 440)
        self.resize(640, 520)

        lv = QVBoxLayout(self)
        acc = theme_colors(app_ref.theme, app_ref.dark)[0]

        controls = QVBoxLayout()
        controls.setSpacing(6)
        metric_row = QHBoxLayout()
        metric_row.setSpacing(10)
        view_row = QHBoxLayout()
        view_row.setSpacing(10)
        self._metric = "hours"
        self._chart_mode = "bar"
        self._hours_radio = QRadioButton(msg("analytics_work_hours"))
        self._avg_radio = QRadioButton(msg("analytics_average"))
        self._hours_radio.setChecked(True)
        self._metric_group = QButtonGroup(self)
        self._metric_group.addButton(self._hours_radio)
        self._metric_group.addButton(self._avg_radio)
        self._hours_radio.toggled.connect(
            lambda checked: checked and self._set_metric("hours"))
        self._avg_radio.toggled.connect(
            lambda checked: checked and self._set_metric("average"))
        self._bar_radio = QRadioButton(msg("analytics_bar"))
        self._line_radio = QRadioButton(msg("analytics_line"))
        self._bar_radio.setChecked(True)
        self._view_group = QButtonGroup(self)
        self._view_group.addButton(self._bar_radio)
        self._view_group.addButton(self._line_radio)
        self._bar_radio.toggled.connect(
            lambda checked: checked and self._set_chart_mode("bar"))
        self._line_radio.toggled.connect(
            lambda checked: checked and self._set_chart_mode("line"))
        for radio in (
            self._hours_radio,
            self._avg_radio,
            self._bar_radio,
            self._line_radio,
        ):
            radio.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._leave_cb = SwitchButton(
            checked=str(app_ref.services.get_setting(
                ANALYTICS_SHOW_LEAVES_SETTING_KEY, "0",
            )) == "1",
            color_on=theme_colors(app_ref.theme, app_ref.dark)[0],
            color_off=switch_off_color(app_ref.dark),
        )
        self._leave_cb.toggled.connect(self._toggle_leave_markers)
        metric_label = QLabel(msg("analytics_metric_label"))
        chart_label = QLabel(msg("analytics_chart_label"))
        leave_label = QLabel(msg("analytics_show_leave"))
        for label in (metric_label, chart_label, leave_label):
            label.setObjectName("muted")
            label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            label.setMinimumWidth(58)
        metric_row.addWidget(metric_label)
        metric_row.addWidget(self._hours_radio)
        metric_row.addWidget(self._avg_radio)
        metric_row.addStretch()
        view_row.addWidget(chart_label)
        view_row.addWidget(self._bar_radio)
        view_row.addWidget(self._line_radio)
        view_row.addSpacing(12)
        view_row.addWidget(leave_label)
        view_row.addWidget(self._leave_cb)
        view_row.addStretch()
        controls.addLayout(metric_row)
        controls.addLayout(view_row)
        lv.addLayout(controls)

        self._tabs_w = QTabWidget()
        self._charts: list[ComboChart] = []
        self._bundles: list[analytics_service.ChartDataBundle] = []

        specs = self._chart_specs()
        for name, bundle, ref in specs:
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setContentsMargins(8, 8, 8, 8)
            chart = ComboChart(
                bundle.bar_data,
                ref=ref,
                dark=app_ref.dark,
                accent=acc,
                line_items=bundle.line_data,
                line_ref=ref,
                leave_indices=bundle.leave_indices,
                leave_items=bundle.leave_hours_data,
                mode=self._chart_mode,
                show_leave_markers=self._leave_cb.isChecked(),
                unit=_("h"),
                no_data=_("No data"),
                bar_label=self._metric_label(),
                line_label=self._metric_label(),
                leave_label=msg("analytics_leave"),
            )
            self._sync_dashed_leave_line(chart, bundle)
            wl.addWidget(chart)
            self._tabs_w.addTab(w, name)
            self._charts.append(chart)
            self._bundles.append(bundle)

        lv.addWidget(self._tabs_w, 1)

        bot = QHBoxLayout()
        bot.setSpacing(8)
        csv_btn = QPushButton("⬇  CSV")
        pdf_btn = QPushButton("⬇  PDF")
        ai_pdf_btn = QPushButton(_("✨ AI PDF"))
        close_btn = QPushButton(_("Close"))
        close_btn.setObjectName("primary_btn")
        csv_btn.clicked.connect(self._export_csv)
        pdf_btn.clicked.connect(self._export_pdf)
        ai_pdf_btn.clicked.connect(self._export_pdf_with_ai)
        close_btn.clicked.connect(self.accept)
        bot.addWidget(csv_btn)
        bot.addWidget(pdf_btn)
        bot.addWidget(ai_pdf_btn)
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
        from calendar import monthrange
        last_day = monthrange(y, m)[1]
        records_by_day = {
            record.date: record
            for record in app.services.month_records(f"{y}-{m:02d}")
        }
        return analytics_service.monthly_chart_data_v3(
            date(y, m, 1),
            date(y, m, last_day),
            self._metric,
            self._leave_cb.isChecked(),
            # One monthly query avoids per-day SQL calls during chart refresh.
            record_getter=records_by_day.get,
            standard_hours=app.work_hours,
        )

    def _set_chart_mode(self, mode: str) -> None:
        self._chart_mode = mode
        for chart in self._charts:
            chart.set_mode(mode)

    def _toggle_leave_markers(self, enabled: bool) -> None:
        self._app.services.set_setting(
            ANALYTICS_SHOW_LEAVES_SETTING_KEY,
            "1" if enabled else "0",
        )
        self._refresh_chart_data()
        for chart in self._charts:
            chart.set_show_leave_markers(enabled)

    def _metric_label(self) -> str:
        return msg("analytics_average") if self._metric == "average" else msg("analytics_work_hours")

    def _set_metric(self, metric: str) -> None:
        if metric == self._metric:
            return
        self._metric = metric
        self._refresh_chart_data()

    def _chart_specs(self):
        app = self._app
        mt = app._safe_float_setting(MONTHLY_TARGET_SETTING_KEY, app.work_hours * 21)
        if self._metric == "average":
            refs = (app.work_hours, app.work_hours * 5, app.work_hours)
        else:
            refs = (mt / 4.3, mt * 3, mt)
        return [
            (msg("analytics_monthly"), self._monthly_data(), refs[0]),
            (_("Quarterly"), self._quarterly_data(), refs[1]),
            (_("Annual"), self._annual_data(), refs[2]),
        ]

    def _sync_dashed_leave_line(self, chart: ComboChart, bundle) -> None:
        chart.clear_dashed_lines()
        if self._leave_cb.isChecked():
            chart.add_dashed_line(
                bundle.leave_line_data,
                ANALYTICS_LEAVE_LINE_COLOR,
                Qt.DashLine,
                msg("analytics_leave"),
            )

    def _refresh_chart_data(self) -> None:
        specs = self._chart_specs()
        self._bundles = []
        for idx, (_name, bundle, ref) in enumerate(specs):
            chart = self._charts[idx]
            chart.set_reference(ref)
            chart.set_series_labels(self._metric_label(), self._metric_label())
            chart.set_data(
                bundle.bar_data,
                bundle.line_data,
                bundle.leave_indices,
                bundle.leave_hours_data,
            )
            self._sync_dashed_leave_line(chart, bundle)
            self._bundles.append(bundle)

    def _quarterly_data(self):
        app = self._app
        y = app.current.year
        return analytics_service.quarterly_chart_data_v3(
            app.services.month_records,
            y,
            self._metric,
            self._leave_cb.isChecked(),
            standard_hours=app.work_hours,
        )

    def _annual_data(self):
        app = self._app
        y = app.current.year
        return analytics_service.annual_chart_data_v3(
            app.services.month_records,
            y,
            self._month_labels(),
            self._metric,
            self._leave_cb.isChecked(),
            standard_hours=app.work_hours,
        )

    def _month_labels(self) -> list[str]:
        return [
            _("Jan"), _("Feb"), _("Mar"), _("Apr"), _("May"), _("Jun"),
            _("Jul"), _("Aug"), _("Sep"), _("Oct"), _("Nov"), _("Dec"),
        ]

    def _monthly_detail(self):
        app = self._app
        y, m = app.current.year, app.current.month
        rows = []
        wk_map = {"normal": "wt_normal", "remote": "wt_remote",
                  "business_trip": "wt_business", "paid_leave": "wt_paid",
                  "comp_leave": "wt_comp", "sick_leave": "wt_sick"}
        wk_fallback = {
            "wt_normal": "Normal",
            "wt_remote": "Remote work",
            "wt_business": "Business trip",
            "wt_paid": "Paid leave",
            "wt_comp": "Comp leave",
            "wt_sick": "Sick leave",
        }
        for rec in sorted(app.services.month_records(f"{y}-{m:02d}"),
                          key=lambda r: r.date):
            wt = rec.safe_work_type()
            h = calc_hours(rec.start, rec.end, rec.break_hours) if rec.has_times else 0.0
            ot = 0.0 if rec.is_leave else max(h - app.work_hours, 0)
            overnight_suffix = (
                f" ({_("Night")})"
                if rec.is_overnight and rec.end else ""
            )
            rows.append({"date": rec.date,
                         "start": rec.start or "—",
                         "end": (rec.end or "—") + overnight_suffix if rec.end else "—",
                         "h": h, "ot": ot,
                         "wt": msg(
                             wk_map.get(wt, "wt_normal"),
                             wk_fallback.get(wk_map.get(wt, "wt_normal"), wt),
                         ),
                         "note": rec.safe_note()})
        return rows

    def _quarterly_detail(self):
        app = self._app
        y = app.current.year
        rows = []
        for q in range(1, 5):
            tot = ot = wd = ld = 0.0
            for m in range((q-1)*3+1, q*3+1):
                a, b, c, d, _avg = self._month_stats(y, m)
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
        y = app.current.year
        rows = []
        labels = self._month_labels()
        for m in range(1, 13):
            total, ot, wd, ld, avg = self._month_stats(y, m)
            rows.append({"m": labels[m-1], "total": total,
                         "ot": ot, "wd": wd, "ld": ld, "avg": avg})
        return rows

    def _current(self):
        i = self._tabs_w.currentIndex()
        return self._bundles[i], self._charts[i]

    def _default_pdf_name(self):
        app = self._app
        y, m = app.current.year, app.current.month
        ts = dt.now().strftime("%Y%m%d_%H%M%S")
        idx = self._tabs_w.currentIndex()
        sfx = [f"monthly_{y}{m:02d}", f"quarterly_{y}", f"annual_{y}"][idx]
        return f"worklog_{sfx}_{ts}.pdf"

    def _export_csv(self):
        bundle, _chart_widget = self._current()
        ts = dt.now().strftime("%Y%m%d_%H%M%S")
        path, _dialog_filter = QFileDialog.getSaveFileName(
            self, _("Export") + " CSV", f"chart_{ts}.csv", "CSV (*.csv)")
        if not path:
            return
        unit = _("h")
        analytics_service.export_chart_csv(
            path,
            bundle,
            msg("period"),
            f"{self._metric_label()} ({unit})",
            f"{msg('analytics_leave_hours')} ({unit})",
        )
        QMessageBox.information(self, _("Export"), _("Saved: {}").format(path))

    def _analytics_launch_kwargs(self) -> dict:
        app = self._app
        idx = self._tabs_w.currentIndex()
        current_bundle, _chart_widget = self._current()
        return {
            "year": app.current.year,
            "month": app.current.month,
            "metric": self._metric_label(),
            "chart_mode": msg("analytics_line") if self._chart_mode == "line" else msg("analytics_bar"),
            "include_leave": self._leave_cb.isChecked(),
            "monthly_bundle": self._bundles[0] if len(self._bundles) > 0 else None,
            "quarterly_bundle": self._bundles[1] if len(self._bundles) > 1 else None,
            "annual_bundle": self._bundles[2] if len(self._bundles) > 2 else None,
            "current_bundle": current_bundle,
            "current_tab_index": idx,
            "work_hours": app.work_hours,
            "monthly_target": app._safe_float_setting(
                MONTHLY_TARGET_SETTING_KEY,
                app.work_hours * 21,
            ),
            "month_labels": self._month_labels(),
        }

    def _export_pdf_with_ai(self) -> None:
        launch_ai_assist(
            self,
            self._app,
            AiAssistLaunchConfig(
                period_type="analytics",
                period_label=_("Analytics AI PDF"),
                apply_button_text=_("Use for PDF"),
                use_secondary_ai=True,
                analytics_kwargs=self._analytics_launch_kwargs(),
            ),
            lambda text: self._export_pdf(ai_narrative=text),
        )

    def _export_pdf(self, ai_narrative: str | None = None):
        bundle, chart_widget = self._current()
        app = self._app
        try:
            __import__("PySide6.QtPrintSupport")
        except ImportError:
            QMessageBox.warning(self, _("Export"),
                                _("PDF requires QtPrintSupport. Saving PNG."))
            path, _dialog_filter = QFileDialog.getSaveFileName(
                self, "PNG", "chart.png", "PNG(*.png)")
            if path:
                chart_widget.grab().save(path)
            return
        path, _dialog_filter = QFileDialog.getSaveFileName(
            self, _("Export") + " PDF", self._default_pdf_name(), "PDF (*.pdf)")
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
                MONTHLY_TARGET_SETTING_KEY, app.work_hours * 21),
        )
        try:
            render_pdf(
                path,
                idx,
                tab,
                chart_widget,
                bundle.bar_data,
                detail_fns[idx],
                ctx,
                ai_narrative=ai_narrative,
            )
            QMessageBox.information(
                self, _("Export"), _("Saved: {}").format(path))
        except Exception as exc:
            QMessageBox.critical(self, _("Export"), str(exc))

    def _pdf_monthly(self, p, pw, ph, pt, t, top, ctx):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QBrush, QFont
        from PySide6.QtCore import Qt
        colors = pdf_colors(ctx)
        rows = self._monthly_detail()
        if not rows:
            return
        total, ot, wd, ld, avg = self._month_stats(
            ctx.year, ctx.month)
        cols = [(_("Monthly total"), f"{total:.1f}{_("h")}"),
                (_("Overtime"),    f"{ot:.1f}{_("h")}"),
                (_("Daily avg"),   f"{avg:.1f}{_("h")}"),
                (_("Work days"),  f"{int(wd)}{_(" days")}"),
                (_("Leave days"), f"{int(ld)}{_(" days")}")]
        box_h = pt(34)
        cw2 = pw / len(cols)
        p.setBrush(QBrush(QColor(colors.panel_bg)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, top, pw, box_h), pt(6), pt(6))
        for i, (k, v) in enumerate(cols):
            cx = i * cw2
            fk = QFont("sans-serif")
            fk.setPixelSize(pt(8))
            p.setFont(fk)
            p.setPen(QColor(colors.muted))
            p.drawText(QRectF(cx, top+pt(4), cw2, pt(12)), Qt.AlignCenter, k)
            fv = QFont("sans-serif")
            fv.setPixelSize(pt(11))
            fv.setBold(True)
            p.setFont(fv)
            p.setPen(QColor(colors.text))
            p.drawText(QRectF(cx, top+pt(16), cw2, pt(14)), Qt.AlignCenter, v)
        top += box_h + pt(6)
        hdrs = [("Date", 0.13), (_("Start"), 0.10), (_("End"), 0.10),
                (_("h"), 0.09), ("OT", 0.09), (_("Work type"), 0.16), (_("Notes"), 0.33)]
        rh = pt(16)
        p.setBrush(QBrush(QColor(colors.panel_header_bg)))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, top, pw, rh))
        fh = QFont("sans-serif")
        fh.setPixelSize(pt(8))
        fh.setBold(True)
        p.setFont(fh)
        p.setPen(QColor(colors.text))
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
            bg = QColor(colors.row_alt_bg if i % 2 == 0 else colors.row_bg)
            p.setBrush(QBrush(bg))
            p.setPen(Qt.NoPen)
            rh2 = pt(13)
            p.drawRect(QRectF(0, top, pw, rh2))
            p.setFont(fr)
            p.setPen(QColor(colors.text))
            vals = [row["date"], row["start"], row["end"],
                    f"{row['h']:.1f}" if row["h"] else "—",
                    f"+{row['ot']:.1f}" if row["ot"] > 0 else "—",
                    row["wt"], row["note"][:30]]
            x = 0
            for val, (_label, frac) in zip(vals, hdrs):
                cw = pw*frac
                p.drawText(QRectF(x+pt(2), top, cw-pt(4), rh2),
                           Qt.AlignVCenter | Qt.AlignLeft, str(val))
                x += cw
            top += rh2
            if top > ph - pt(24):
                fi = QFont("sans-serif")
                fi.setPixelSize(pt(8))
                p.setFont(fi)
                p.setPen(QColor(colors.disabled))
                p.drawText(QRectF(0, top+pt(4), pw, pt(12)), Qt.AlignCenter,
                           f"… {len(rows)-i-1} more rows")
                break

    def _pdf_quarterly(self, p, pw, ph, pt, t, top, ctx):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QBrush, QFont
        from PySide6.QtCore import Qt
        colors = pdf_colors(ctx)
        rows = self._quarterly_detail()
        hdrs = [("Quarter", 0.15), (_("Monthly total"), 0.17), (_("Overtime"), 0.17),
                (_("Daily avg"), 0.17), (_("Work days"), 0.17), (_("Leave days"), 0.17)]
        rh = pt(16)
        p.setBrush(QBrush(QColor(colors.panel_header_bg)))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, top, pw, rh))
        fh = QFont("sans-serif")
        fh.setPixelSize(pt(8))
        fh.setBold(True)
        p.setFont(fh)
        p.setPen(QColor(colors.text))
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
            bg = QColor(colors.row_alt_bg if i % 2 == 0 else colors.row_bg)
            p.setBrush(QBrush(bg))
            p.setPen(Qt.NoPen)
            rh2 = pt(20)
            p.drawRect(QRectF(0, top, pw, rh2))
            p.setFont(fr)
            p.setPen(QColor(colors.text))
            vals = [row["q"], f"{row['total']:.1f}{_("h")}",
                    f"{row['ot']:.1f}{_("h")}", f"{row['avg']:.1f}{_("h")}",
                    f"{row['wd']}{_(" days")}", f"{row['ld']}{_(" days")}"]
            x = 0
            for val, (_label, frac) in zip(vals, hdrs):
                cw = pw*frac
                p.drawText(QRectF(x+pt(3), top, cw-pt(6), rh2),
                           Qt.AlignVCenter | Qt.AlignLeft, str(val))
                x += cw
            top += rh2

    def _pdf_annual(self, p, pw, ph, pt, t, top, ctx):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QBrush, QFont
        from PySide6.QtCore import Qt
        colors = pdf_colors(ctx)
        s = [self._month_stats(ctx.year, m) for m in range(1, 13)]
        total = sum(x[0] for x in s)
        ot = sum(x[1] for x in s)
        wd = sum(x[2] for x in s)
        ld = sum(x[3] for x in s)
        avg = total/wd if wd else 0.0
        cols = [(_("Monthly total"), f"{total:.1f}{_("h")}"), (_("Overtime"), f"{ot:.1f}{_("h")}"),
                (_("Daily avg"), f"{avg:.1f}{_("h")}"), (
                    _("Work days"), f"{int(wd)}{_(" days")}"),
                (_("Leave days"), f"{int(ld)}{_(" days")}")]
        box_h = pt(34)
        cw2 = pw/len(cols)
        p.setBrush(QBrush(QColor(colors.panel_bg)))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(0, top, pw, box_h), pt(6), pt(6))
        for i, (k, v) in enumerate(cols):
            cx = i*cw2
            fk = QFont("sans-serif")
            fk.setPixelSize(pt(8))
            p.setFont(fk)
            p.setPen(QColor(colors.muted))
            p.drawText(QRectF(cx, top+pt(4), cw2, pt(12)), Qt.AlignCenter, k)
            fv = QFont("sans-serif")
            fv.setPixelSize(pt(11))
            fv.setBold(True)
            p.setFont(fv)
            p.setPen(QColor(colors.text))
            p.drawText(QRectF(cx, top+pt(16), cw2, pt(14)), Qt.AlignCenter, v)
        top += box_h+pt(6)
        rows = self._annual_detail()
        hdrs = [("Month", 0.12), (_("Monthly total"), 0.17), (_("Overtime"), 0.17),
                (_("Daily avg"), 0.17), (_("Work days"), 0.17), (_("Leave days"), 0.20)]
        rh = pt(16)
        p.setBrush(QBrush(QColor(colors.panel_header_bg)))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(0, top, pw, rh))
        fh = QFont("sans-serif")
        fh.setPixelSize(pt(8))
        fh.setBold(True)
        p.setFont(fh)
        p.setPen(QColor(colors.text))
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
            bg = QColor(colors.row_alt_bg if i % 2 == 0 else colors.row_bg)
            p.setBrush(QBrush(bg))
            p.setPen(Qt.NoPen)
            rh2 = pt(17)
            p.drawRect(QRectF(0, top, pw, rh2))
            p.setFont(fr)
            p.setPen(QColor(colors.text if row["total"] > 0 else colors.disabled))
            vals = [row["m"], f"{row['total']:.1f}{_("h")}", f"{row['ot']:.1f}{_("h")}",
                    f"{row['avg']:.1f}{_("h")}", f"{row['wd']}{_(" days")}", f"{row['ld']}{_(" days")}"]
            x = 0
            for val, (_label, frac) in zip(vals, hdrs):
                cw = pw*frac
                p.drawText(QRectF(x+pt(3), top, cw-pt(6), rh2),
                           Qt.AlignVCenter | Qt.AlignLeft, str(val))
                x += cw
            top += rh2


class QuickLogDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        self.setWindowTitle(_("Quick Log"))
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
        dow = [_("Sun"), _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat")][(d.weekday() + 1) % 7]
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

        lbl = QLabel(_("Today's entries:"))
        lbl.setObjectName("muted")
        lft.addWidget(lbl)

        self._list = QListWidget()
        self._list.setObjectName("quick_log_list")
        self._list.setAlternatingRowColors(False)
        self._list.setSpacing(0)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setStyleSheet(quick_log_list_qss())
        self._list.itemClicked.connect(self._load_for_edit)
        self._list.currentItemChanged.connect(self._on_list_current_changed)
        lft.addWidget(self._list, 1)

        right_w = QWidget()
        rgt = QVBoxLayout(right_w)
        rgt.setContentsMargins(4, 0, 0, 0)
        rgt.setSpacing(8)

        time_lbl = QLabel(_("Time"))
        time_lbl.setObjectName("muted")
        rgt.addWidget(time_lbl)

        now_str = _dt.now().strftime("%H:%M")

        time_row = QHBoxLayout()
        time_row.setSpacing(4)
        self._clk_start_btn = QPushButton(_("Clock"))
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
        self._end_in.setPlaceholderText(_("End time (opt.)"))
        self._end_in.setFixedWidth(85)
        self._end_in.editingFinished.connect(
            lambda: self._normalise_time(self._end_in))

        self._clk_end_btn = QPushButton(_("Clock"))
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

        desc_lbl = QLabel(_("What are you doing?"))
        desc_lbl.setObjectName("muted")
        rgt.addWidget(desc_lbl)

        self._desc_in = QLineEdit()
        self._desc_in.setPlaceholderText(_("What are you doing?"))
        self._desc_in.returnPressed.connect(self._add_entry)
        rgt.addWidget(self._desc_in)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._add_btn = QPushButton(msg("quick_log_add"))
        self._add_btn.setObjectName("primary_btn")
        self._add_btn.clicked.connect(self._add_entry)
        self._cancel_edit_btn = QPushButton(_("Close"))
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
        hint_lbl = QLabel(_("Quick logs appear in daily notes and AI reports."))
        hint_lbl.setObjectName("muted")
        hint_lbl.setWordWrap(True)
        close_btn = QPushButton(_("Close"))
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
            field.setStyleSheet(line_edit_error_qss())

    def _refresh_list(self):
        d_str = self._app.selected.isoformat()
        self._row_widgets.clear()
        self._list.setUpdatesEnabled(False)
        self._list.clear()
        entries = self._app.services.quick_logs_for_date(d_str)
        hover_color = theme_colors(self._app.theme, self._app.dark)[1]
        if not entries:
            placeholder = QListWidgetItem(_("No entries yet today."))
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
                text_lbl.setTextFormat(Qt.PlainText)
                text_lbl.setSizePolicy(
                    QSizePolicy.Expanding, QSizePolicy.Preferred)
                text_lbl.setCursor(Qt.PointingHandCursor)
                text_lbl.setToolTip(escape(full_text, quote=True))
                text_lbl.setStyleSheet(quick_log_label_hover_qss(hover_color))
                text_lbl.mousePressEvent = lambda e, it=item, ent=entry: self._activate_row(
                    it, ent)
                row_l.addWidget(text_lbl, 1)
                x_btn = QPushButton("✕")
                x_btn.setStyleSheet(quick_log_delete_button_qss())
                x_btn.setFixedSize(18, 18)
                x_btn.setToolTip(msg("quick_log_delete"))
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
        acc, _acc_hov, acc_dim, hov, _stat_bd = theme_colors(
            self._app.theme,
            self._app.dark,
        )
        txt = quick_log_text_color(self._app.dark)
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
                    quick_log_row_qss(
                        "selected",
                        accent=acc,
                        accent_dim=acc_dim,
                        hover=hov,
                    )
                )
                text_lbl.setStyleSheet(label_color_qss(txt))
            elif is_hovered:
                row_w.setStyleSheet(
                    quick_log_row_qss(
                        "hover",
                        accent=acc,
                        accent_dim=acc_dim,
                        hover=hov,
                    )
                )
                text_lbl.setStyleSheet("")
            else:
                row_w.setStyleSheet(
                    quick_log_row_qss(
                        "default",
                        accent=acc,
                        accent_dim=acc_dim,
                        hover=hov,
                    )
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
        self._editing_id = entry["id"]
        self._time_in.setText(entry["time"])
        self._end_in.setText(entry.get("end_time", "") or "")
        self._desc_in.setText(entry["description"])
        self._desc_in.setFocus()
        self._add_btn.setText(_("Save"))
        self._cancel_edit_btn.setVisible(True)
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) and item.data(Qt.UserRole)["id"] == entry["id"]:
                self._list.setCurrentRow(i)
                break

    def _cancel_edit(self):
        self._editing_id = None
        from datetime import datetime as _dt
        self._time_in.setText(_dt.now().strftime("%H:%M"))
        self._end_in.clear()
        self._desc_in.clear()
        self._add_btn.setText(msg("quick_log_add"))
        self._cancel_edit_btn.setVisible(False)
        self._list.clearSelection()
        self._sync_row_styles()

    def _add_entry(self):
        desc = self._desc_in.text().strip()
        if not desc:
            self._desc_in.setFocus()
            self._desc_in.setStyleSheet(line_edit_error_qss())
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
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Quick Log"))
        box.setText(_("Delete this entry?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _localize_msgbox_buttons(box, _)
        if box.exec() != QMessageBox.Yes:
            return
        self._app.services.delete_quick_log(log_id)
        if self._editing_id == log_id:
            self._cancel_edit()
        self._refresh_list()
