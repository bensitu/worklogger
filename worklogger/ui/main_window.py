"""Main application window."""

from __future__ import annotations
import sys
import threading
from datetime import datetime, date, timedelta
from calendar import monthrange

from PySide6.QtWidgets import (
    QApplication, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QGridLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QTabWidget,
    QFileDialog, QMessageBox, QComboBox, QSizePolicy, QSystemTrayIcon, QMenu,
)
from PySide6.QtCore import Qt, QTimer, Slot, QEvent
from PySide6.QtGui import QColor, QPainter, QAction

from config.i18n import T, LANG_KEYS, LANG_NAMES
from config.themes import make_qss, cell_pool, THEMES, THEME_KEYS, WT_BORDER_ACCENT
from config.constants import WORK_TYPE_KEYS, LEAVE_TYPES
from core.time_calc import calc_hours, detect_country
from core.validator import parse_time
from services.app_services import AppServices
from stores.app_store import AppStore, AppState
from ui.dialogs import (
    SettingsDialog, NoteEditorDialog, ReportDialog, ChartDialog,
    QuickLogDialog,
)
from utils.icon import make_icon

STYLE_PRIO = ["weekend", "today", "holiday", "selected"]
REQUIRED_COLS = {"date", "start", "end", "break", "note"}


def _localize_msgbox_buttons(box: QMessageBox, t: dict) -> QMessageBox:
    """Apply translated labels to common standard message box buttons."""
    mapping = {
        QMessageBox.StandardButton.Yes: t.get("btn_yes", "Yes"),
        QMessageBox.StandardButton.No: t.get("btn_no", "No"),
        QMessageBox.StandardButton.Save: t.get("save", "Save"),
        QMessageBox.StandardButton.Discard: t.get("btn_discard", "Discard"),
        QMessageBox.StandardButton.Cancel: t.get("btn_cancel", "Cancel"),
    }
    for button, label in mapping.items():
        btn = box.button(button)
        if btn:
            btn.setText(label)
    return box


class CalendarDayButton(QPushButton):
    """Calendar cell button with an optional note marker in the top-left corner."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._show_note_marker = False
        self._marker_color = "#4f8ef7"

    def set_note_marker(self, visible: bool, color: str) -> None:
        self._show_note_marker = visible
        self._marker_color = color
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._show_note_marker:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._marker_color))
        p.drawEllipse(7, 7, 7, 7)
        p.end()


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.services = AppServices()
        self.today = date.today()
        self.current = self.today.replace(day=1)
        self.selected = self.today

        saved_lang = self.services.get_setting("lang",  "en")
        saved_theme = self.services.get_setting("theme", "blue")
        self.lang = saved_lang if saved_lang in LANG_KEYS else "en"
        self.theme = saved_theme if saved_theme in THEME_KEYS else "blue"
        self.dark = self.services.get_setting("dark", "0") == "1"
        if self.services.get_setting("work_hours") is None:
            self.services.set_setting("work_hours", "8.0")
        legacy_default_break = self.services.get_setting("default_lunch")
        if self.services.get_setting("default_break") is None:
            self.services.set_setting("default_break", legacy_default_break or "1.0")
        if self.services.get_setting("monthly_target") is None:
            self.services.set_setting("monthly_target", str(round(8.0 * 21, 1)))
        self.work_hours = self._safe_float_setting("work_hours", 8.0)
        if self.services.get_setting("show_holidays") is None:
            self.services.set_setting("show_holidays", "1")
        if self.services.get_setting("show_note_markers") is None:
            self.services.set_setting("show_note_markers", "1")
        residency_key = self._residency_setting_key()
        if residency_key and self.services.get_setting(residency_key) is None:
            self.services.set_setting(residency_key, "0")

        self.holidays: dict = {}
        self._country = detect_country()
        self._day_btns:    list[QPushButton] = []
        self._week_totals: list[QLabel] = []
        self._break_start: datetime | None = None
        self._break_timer: QTimer | None = None
        self._active_time_tab = self.services.get_setting(
            "time_input_mode", "manual")
        self._auto_start_time = ""
        self._auto_end_time = ""
        self._auto_break_hours = self._safe_float_setting("default_break", 1.0)
        self._auto_break_recorded = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_quit_requested = False
        self.store = AppStore(AppState(
            lang=self.lang,
            theme=self.theme,
            dark=self.dark,
            work_hours=self.work_hours,
            default_break=self._auto_break_hours,
            monthly_target=self._safe_float_setting("monthly_target", self.work_hours * 21),
            show_holidays=self.services.get_setting("show_holidays", "1") == "1",
            show_note_markers=self.services.get_setting("show_note_markers", "1") == "1",
            week_start_monday=self.services.get_setting("week_start_monday", "0") == "1",
            time_input_mode=self._active_time_tab,
        ))

        self._build_ui()
        self._setup_residency_icon()
        self.apply_theme()
        self.apply_lang()
        self.load()
        self.render()

        QTimer.singleShot(0, self._load_holidays)

    def _load_holidays(self):
        """Load holiday data in a background thread to avoid blocking UI.
        Uses a QTimer on the main thread to safely marshal the result back.
        """
        if self.services.get_setting("show_holidays", "1") == "0":
            self.holidays = {}
            return

        def _fetch():
            try:
                import holidays as hd
                data = hd.country_holidays(self._country)
                if not data:
                    data = hd.country_holidays(self._country,
                                               years=self.today.year)
            except Exception:
                data = {}
            self._holidays_pending = data
            # Marshal the UI update back to the main Qt thread.
            from PySide6.QtCore import QMetaObject, Qt as _Qt
            QMetaObject.invokeMethod(self, "_apply_holidays",
                                     _Qt.ConnectionType.QueuedConnection)

        self._holidays_pending: dict = {}
        threading.Thread(target=_fetch, daemon=True).start()

    @Slot()
    def _apply_holidays(self):
        self.holidays = self._holidays_pending
        self.render()

    def _build_ui(self):
        self.setWindowTitle("Work Logger")
        self.resize(1100, 700)
        self.setMinimumSize(900, 580)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(14, 14, 14, 10)
        lv.setSpacing(6)

        nav = QHBoxLayout()
        nav.setSpacing(6)
        self.prev_btn = QPushButton("◀")
        self.prev_btn.setObjectName("nav_btn")
        self.prev_btn.setFixedWidth(38)
        self.next_btn = QPushButton("▶")
        self.next_btn.setObjectName("nav_btn")
        self.next_btn.setFixedWidth(38)
        self.month_title = QLabel()
        self.month_title.setObjectName("month_title")
        self.month_title.setAlignment(Qt.AlignCenter)
        self.today_btn = QPushButton("◎")
        self.today_btn.setObjectName("nav_btn")
        self.today_btn.setFixedWidth(38)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.month_title, 1)
        nav.addWidget(self.next_btn)
        nav.addSpacing(4)
        nav.addWidget(self.today_btn)
        lv.addLayout(nav)

        self.grid = QGridLayout()
        self.grid.setSpacing(3)
        for c in range(7):
            self.grid.setColumnStretch(c, 4)
        self.grid.setColumnStretch(7, 2)
        self.week_day_lbls: list[QLabel] = []
        for c in range(7):
            lbl = QLabel()
            lbl.setObjectName("week_lbl")
            lbl.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(lbl, 0, c)
            self.week_day_lbls.append(lbl)
        self.week_col_hdr = QLabel()
        self.week_col_hdr.setObjectName("week_lbl")
        self.week_col_hdr.setAlignment(Qt.AlignCenter)
        self.grid.addWidget(self.week_col_hdr, 0, 7)
        lv.addLayout(self.grid)
        lv.addStretch(1)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(326)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(16, 16, 16, 14)
        sv.setSpacing(8)

        self.date_banner = QLabel()
        self.date_banner.setObjectName("date_banner")
        self.date_banner.setAlignment(Qt.AlignCenter)
        sv.addWidget(self.date_banner)
        sv.addSpacing(8)

        self.time_tabs = QTabWidget()
        self.time_tabs.setObjectName("time_tabs")
        self.time_tabs.setDocumentMode(True)

        self.manual_tab = QWidget()
        self.manual_tab.setObjectName("time_tab_panel")
        self.auto_tab = QWidget()
        self.auto_tab.setObjectName("time_tab_panel")
        self.time_tabs.addTab(self.manual_tab, "")
        self.time_tabs.addTab(self.auto_tab, "")
        sv.addWidget(self.time_tabs)

        manual_layout = QVBoxLayout(self.manual_tab)
        manual_layout.setContentsMargins(10, 2, 10, 5)
        manual_layout.setSpacing(3)

        def manual_field(label_attr: str, input_attr: str, placeholder: str):
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel()
            lbl.setObjectName("muted")
            setattr(self, label_attr, lbl)
            lbl.setFixedWidth(52)
            lbl.setFixedHeight(28)
            widget = QLineEdit()
            widget.setPlaceholderText(placeholder)
            widget.setFixedHeight(28)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            setattr(self, input_attr, widget)
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            manual_layout.addLayout(row)

        manual_field("manual_lbl_start", "manual_start_in", "HH:MM")
        manual_field("manual_lbl_end", "manual_end_in", "HH:MM")
        lunch_manual_row = QHBoxLayout()
        lunch_manual_row.setSpacing(8)
        self.manual_lbl_break = QLabel()
        self.manual_lbl_break.setObjectName("muted")
        self.manual_lbl_break.setFixedWidth(52)
        self.manual_break_in = QLineEdit("1.0")
        self.manual_break_in.setPlaceholderText("1.0")
        self.manual_break_in.setFixedHeight(28)
        lunch_manual_row.addWidget(self.manual_lbl_break)
        lunch_manual_row.addWidget(self.manual_break_in, 1)
        manual_layout.addLayout(lunch_manual_row)

        auto_layout = QVBoxLayout(self.auto_tab)
        auto_layout.setContentsMargins(10, 2, 10, 5)
        auto_layout.setSpacing(6)

        auto_buttons_row = QHBoxLayout()
        auto_buttons_row.setSpacing(10)

        def auto_column(label_attr: str, btn_attr: str):
            col = QVBoxLayout()
            col.setSpacing(6)
            lbl = QLabel()
            lbl.setObjectName("muted")
            lbl.setAlignment(Qt.AlignCenter)
            setattr(self, label_attr, lbl)
            btn = QPushButton()
            btn.setObjectName("clock_btn")
            btn.setMinimumSize(64, 70)
            btn.setMaximumHeight(80)
            setattr(self, btn_attr, btn)
            col.addWidget(lbl)
            col.addWidget(btn)
            auto_buttons_row.addLayout(col, 1)

        auto_column("auto_lbl_start", "clock_in_btn")
        auto_column("auto_lbl_end", "clock_out_btn")
        auto_column("auto_lbl_break", "break_btn")
        auto_layout.addLayout(auto_buttons_row)
        self.break_btn.installEventFilter(self)

        initial_tab = 1 if self._active_time_tab == "auto" else 0
        self.time_tabs.setCurrentIndex(initial_tab)
        QTimer.singleShot(0, self._sync_time_tab_widths)

        self.lbl_wt = QLabel()
        self.lbl_wt.setObjectName("muted")
        sv.addWidget(self.lbl_wt)
        self.wt_combo = QComboBox()
        sv.addWidget(self.wt_combo)

        note_hdr = QHBoxLayout()
        self.lbl_note = QLabel()
        self.lbl_note.setObjectName("muted")
        self.note_expand_btn = QPushButton("⤢")
        self.note_expand_btn.setObjectName("nav_btn")
        self.note_expand_btn.setFixedSize(26, 22)
        self.note_expand_btn.setToolTip("")
        note_hdr.addWidget(self.lbl_note, 1)
        note_hdr.addWidget(self.note_expand_btn)
        sv.addLayout(note_hdr)
        self.note_in = QTextEdit()
        self.note_in.setFixedHeight(74)
        sv.addWidget(self.note_in)

        sv.addSpacing(4)
        self.save_btn = QPushButton()
        self.save_btn.setObjectName("primary_btn")
        self.save_btn.setMinimumHeight(38)
        sv.addWidget(self.save_btn)

        self.quick_log_btn = QPushButton()
        self.quick_log_btn.setObjectName("action_btn")
        self.quick_log_btn.setMinimumHeight(36)
        sv.addWidget(self.quick_log_btn)
        sv.addWidget(self._div())

        stat_card = QFrame()
        stat_card.setObjectName("stat_card")
        sc = QVBoxLayout(stat_card)
        sc.setContentsMargins(12, 10, 12, 10)
        sc.setSpacing(5)

        def stat_row(ka, va, is_ot=False, underline=False):
            h = QHBoxLayout()
            h.setSpacing(4)
            k = QLabel()
            k.setObjectName("stat_key")
            obj = "stat_val_ot" if is_ot else (
                "stat_val_leave" if underline else "stat_val")
            v = QLabel()
            v.setObjectName(obj)
            setattr(self, ka, k)
            setattr(self, va, v)
            h.addWidget(k, 1)
            h.addWidget(v)
            sc.addLayout(h)

        stat_row("sk_total", "sv_total")
        stat_row("sk_ot",    "sv_ot",   is_ot=True)
        stat_row("sk_avg",   "sv_avg")
        stat_row("sk_days",  "sv_days",  underline=True)
        stat_row("sk_leave", "sv_leave", underline=True)
        sv.addWidget(stat_card)

        sv.addSpacing(4)
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("action_btn")
        sv.addWidget(self.settings_btn)

        act_row = QHBoxLayout()
        act_row.setSpacing(6)
        self.report_btn = QPushButton()
        self.report_btn.setObjectName("action_btn")
        self.chart_btn = QPushButton()
        self.chart_btn.setObjectName("action_btn")
        act_row.addWidget(self.report_btn)
        act_row.addWidget(self.chart_btn)
        sv.addLayout(act_row)
        sv.addStretch()

        root.addWidget(left, 1)
        root.addWidget(sidebar)

        self.prev_btn.clicked.connect(self.prev_m)
        self.next_btn.clicked.connect(self.next_m)
        self.today_btn.clicked.connect(self.go_today)
        self.save_btn.clicked.connect(self.save)
        self.clock_in_btn.clicked.connect(
            lambda: self._set_auto_time("start"))
        self.clock_out_btn.clicked.connect(
            lambda: self._set_auto_time("end"))
        self.break_btn.clicked.connect(self._toggle_break)
        self.time_tabs.currentChanged.connect(self._on_time_tab_changed)
        self.note_expand_btn.clicked.connect(self.open_note_editor)
        self.settings_btn.clicked.connect(self.open_settings)
        self.report_btn.clicked.connect(self.open_report)
        self.chart_btn.clicked.connect(self.open_chart)
        self.quick_log_btn.clicked.connect(self.open_quick_log)

    def _div(self):
        f = QFrame()
        f.setObjectName("divider")
        return f

    def _safe_float_setting(self, key: str, default: float) -> float:
        """Read a float setting with a safe fallback for malformed values."""
        try:
            return float(self.services.get_setting(key, str(default)))
        except (TypeError, ValueError):
            return default

    def _residency_setting_key(self) -> str | None:
        if sys.platform == "win32":
            return "enable_tray"
        if sys.platform == "darwin":
            return "enable_menu_bar"
        return None

    def _residency_enabled(self) -> bool:
        key = self._residency_setting_key()
        if not key:
            return False
        return self.services.get_setting(key, "0") == "1"

    def _setup_residency_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QApplication.instance().setQuitOnLastWindowClosed(True)
            return
        icon = self.windowIcon()
        if icon.isNull():
            icon = QApplication.instance().windowIcon()
        if icon.isNull():
            icon = make_icon()
        self._tray_icon = QSystemTrayIcon(icon, self)
        menu = QMenu()
        self._tray_open_action = QAction("", self)
        self._tray_open_action.triggered.connect(self._restore_from_tray)
        self._tray_quick_log_action = QAction("", self)
        self._tray_quick_log_action.triggered.connect(
            self._open_quick_log_from_tray)
        self._tray_quit_action = QAction("", self)
        self._tray_quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(self._tray_open_action)
        menu.addAction(self._tray_quick_log_action)
        menu.addSeparator()
        menu.addAction(self._tray_quit_action)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._update_residency_state()

    def _update_residency_state(self):
        enabled = self._residency_enabled() and QSystemTrayIcon.isSystemTrayAvailable()
        QApplication.instance().setQuitOnLastWindowClosed(not enabled)
        if not self._tray_icon:
            return
        t = T[self.lang]
        self._tray_open_action.setText(t["tray_open"])
        self._tray_quick_log_action.setText(t["tray_quick_log"])
        self._tray_quit_action.setText(t["tray_quit"])
        self._tray_icon.setToolTip(t["app_title"])
        if enabled:
            self._tray_icon.show()
        else:
            self._tray_icon.hide()

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _open_quick_log_from_tray(self):
        self._restore_from_tray()
        self.open_quick_log()

    def _quit_from_tray(self):
        self._tray_quit_requested = True
        if self._tray_icon:
            self._tray_icon.hide()
        QApplication.instance().quit()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._restore_from_tray()

    def apply_theme(self):
        QApplication.instance().setStyleSheet(make_qss(self.dark, self.theme))

    def apply_lang(self):
        t = T[self.lang]
        self.setWindowTitle(t["app_title"])
        self.time_tabs.setTabText(0, t.get("time_manual_tab", "Manual Input"))
        self.time_tabs.setTabText(1, t.get("time_auto_tab", "Auto Record"))
        self.manual_lbl_start.setText(t["start"])
        self.manual_lbl_end.setText(t["end"])
        self.manual_lbl_break.setText(t["break_h"])
        self.manual_start_in.setPlaceholderText(
            t.get("time_placeholder_start", "HH:MM"))
        self.manual_end_in.setPlaceholderText(
            t.get("time_placeholder_end", "HH:MM"))
        self.manual_break_in.setPlaceholderText(
            t.get("time_placeholder_break", "1.0"))
        self.auto_lbl_start.setText(t["start"])
        self.auto_lbl_end.setText(t["end"])
        self.auto_lbl_break.setText(t["break_h"])
        self.lbl_wt.setText(t["wt_label"])
        self.lbl_note.setText(t["note"])
        self.clock_in_btn.setText(t.get("start_now", t["start"]))
        self.clock_out_btn.setText(t.get("end_now", t["end"]))
        self.save_btn.setText(t["save"])
        self.settings_btn.setText(t["btn_settings"])
        self.report_btn.setText(t["btn_report"])
        self.chart_btn.setText(t["btn_chart"])
        self.quick_log_btn.setText(t["quick_log_btn"])
        self.today_btn.setToolTip(t["today_tip"])
        self.note_expand_btn.setToolTip(t["note_expand_tip"])
        # Respect user preference for week start (Sunday vs Monday)
        week_start_monday = self.services.get_setting("week_start_monday", "0") == "1"
        days_list = list(t["days"])
        if week_start_monday:
            # rotate so Monday is first
            days_list = days_list[1:] + days_list[:1]
        for i, lbl in enumerate(self.week_day_lbls):
            lbl.setText(days_list[i])
        self.week_col_hdr.setText(t["week_col"])
        self.sk_total.setText(t["stat_total"])
        self.sk_ot.setText(t["stat_ot"])
        self.sk_avg.setText(t["stat_avg"])
        self.sk_days.setText(t["stat_days"])
        self.sk_leave.setText(t["stat_leave"])
        self._refresh_auto_time_labels()
        self._update_residency_state()
        cur_wt = self.wt_combo.currentData() or "normal"
        self.wt_combo.blockSignals(True)
        self.wt_combo.clear()
        wk = {"normal": "wt_normal", "remote": "wt_remote", "business_trip": "wt_business",
              "paid_leave": "wt_paid", "comp_leave": "wt_comp", "sick_leave": "wt_sick"}
        for key in WORK_TYPE_KEYS:
            self.wt_combo.addItem(t[wk[key]], key)
        idx = self.wt_combo.findData(cur_wt)
        if idx >= 0:
            self.wt_combo.setCurrentIndex(idx)
        self.wt_combo.blockSignals(False)
        self._update_banner()

    def _update_banner(self):
        d = self.selected
        # Map weekday name according to week-start preference
        week_start_monday = self.services.get_setting("week_start_monday", "0") == "1"
        if week_start_monday:
            dow = T[self.lang]["days"][d.weekday()]
        else:
            dow = T[self.lang]["days"][(d.weekday() + 1) % 7]
        self.date_banner.setText(f"{d.year}/{d.month:02d}/{d.day:02d}  {dow}")

    def _time_mode(self) -> str:
        return "auto" if self.time_tabs.currentIndex() == 1 else "manual"

    def _on_time_tab_changed(self, index: int):
        self._active_time_tab = "auto" if index == 1 else "manual"
        self.services.set_setting("time_input_mode", self._active_time_tab)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_time_tab_widths()

    def _sync_time_tab_widths(self):
        bar = self.time_tabs.tabBar()
        if bar.count() <= 0:
            return
        for i in range(bar.count()):
            bar.setTabButton(i, bar.ButtonPosition.LeftSide, None)
            bar.setTabButton(i, bar.ButtonPosition.RightSide, None)
            bar.setStyleSheet("")
        bar.setExpanding(True)

    def eventFilter(self, obj, event):
        if obj is self.break_btn and event.type() == QEvent.Type.MouseButtonDblClick:
            self._set_quick_break_hour(
                self._safe_float_setting("default_break", 1.0))
            return True
        return super().eventFilter(obj, event)

    def _set_auto_time(self, field_name: str):
        now_str = datetime.now().strftime("%H:%M")
        if field_name == "start":
            self._auto_start_time = now_str
        else:
            self._auto_end_time = now_str
        self._refresh_auto_time_labels()

    def _refresh_auto_time_labels(self):
        t = T[self.lang]
        self.clock_in_btn.setText(
            f"{t.get('start_done', 'Started')}\n{self._auto_start_time}"
            if self._auto_start_time else t.get("start_now", t["start"])
        )
        self.clock_out_btn.setText(
            f"{t.get('end_done', 'Ended')}\n{self._auto_end_time}"
            if self._auto_end_time else t.get("end_now", t["end"])
        )
        if self._break_start is None:
            if self._auto_break_recorded:
                self.break_btn.setText(
                    f"{t.get('break_done', 'Break')}\n{self._auto_break_hours:.1f}{t['h_unit']}"
                )
            else:
                self.break_btn.setText(t["break_start"])

    def _active_time_values(self) -> tuple[str, str, float]:
        if self._time_mode() == "auto":
            start_txt = self._auto_start_time
            end_txt = self._auto_end_time
            break_val = self._auto_break_hours
        else:
            start_txt = self.manual_start_in.text().strip()
            end_txt = self.manual_end_in.text().strip()
            break_txt = self.manual_break_in.text().strip()
            try:
                break_val = float(break_txt) if break_txt else self._safe_float_setting(
                    "default_break", 1.0)
            except (TypeError, ValueError):
                break_val = self._safe_float_setting("default_break", 1.0)
        return start_txt, end_txt, break_val

    def _toggle_break(self):
        if self._break_start is None:
            if self._auto_break_recorded and self._auto_break_hours > 0:
                action = self._ask_break_restart_mode()
                if action == "cancel":
                    return
                if action == "continue":
                    self._start_break_timer(resume=True)
                else:
                    self._start_break_timer(resume=False)
            else:
                self._start_break_timer(resume=False)
        else:
            if self._break_timer:
                self._break_timer.stop()
            elapsed_h = (datetime.now() - self._break_start).seconds / 3600
            elapsed_h = round(elapsed_h * 4) / 4
            self._auto_break_hours = elapsed_h if elapsed_h else 0.0
            self._auto_break_recorded = True
            self._break_start = None
            self._break_timer = None
            self.break_btn.setStyleSheet("")
            self._refresh_auto_time_labels()

    def _start_break_timer(self, resume: bool):
        elapsed = max(self._auto_break_hours, 0.0) if resume else 0.0
        self._break_start = datetime.now() - timedelta(hours=elapsed)
        self._break_timer = QTimer(self)
        self._break_timer.timeout.connect(self._tick_break)
        self._break_timer.start(60_000)
        if not resume:
            self._auto_break_hours = 0.0
            self._auto_break_recorded = False
        self._tick_break()

    def _ask_break_restart_mode(self) -> str:
        t = T[self.lang]
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(t["break_resume_title"])
        box.setText(t["break_resume_msg"].format(
            hours=f"{self._auto_break_hours:.1f}"))
        restart_btn = box.addButton(
            t["break_restart"], QMessageBox.ButtonRole.AcceptRole)
        continue_btn = box.addButton(
            t["break_continue"], QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        _localize_msgbox_buttons(box, t)
        box.setDefaultButton(continue_btn)
        box.exec()
        clicked = box.clickedButton()
        if clicked == continue_btn:
            return "continue"
        if clicked == restart_btn:
            return "restart"
        if clicked == cancel_btn:
            return "cancel"
        return "cancel"

    def _set_quick_break_hour(self, hours: float):
        if self._break_timer:
            self._break_timer.stop()
        self._break_start = None
        self._break_timer = None
        self._auto_break_hours = hours
        self._auto_break_recorded = True
        self.break_btn.setStyleSheet("")
        self._refresh_auto_time_labels()

    def _tick_break(self):
        t = T[self.lang]
        if self._break_start is None:
            return
        mins = (datetime.now() - self._break_start).seconds // 60
        self.break_btn.setText(f"{t.get('break_active', 'On break')}\n{mins}m")
        self._auto_break_hours = mins / 60
        color = "#ffaa44" if self.dark else "#e07800"
        self.break_btn.setStyleSheet(
            f"QPushButton{{color:{color};border-color:{color};}}")

    def _cell_style(self, dt: date):
        pool = cell_pool(self.dark, self.theme)
        flags = {"today": dt == self.today, "selected": dt == self.selected,
                 "weekend": dt.weekday() >= 5, "holiday": dt in self.holidays}
        result = pool["default"]
        for key in STYLE_PRIO:
            if flags[key]:
                result = pool[key]
        return result

    def render(self):
        for w in self._day_btns + self._week_totals:
            self.grid.removeWidget(w)
            w.deleteLater()
        self._day_btns = []
        self._week_totals = []

        y, m = self.current.year, self.current.month
        t = T[self.lang]
        self.month_title.setText(f"{y}  {t['months'][m-1]}")
        raw_first, days = monthrange(y, m)
        week_start_monday = self.store.state.week_start_monday
        first = raw_first if week_start_monday else (raw_first + 1) % 7

        # ── ONE query for the whole month (was N+1) ──────────────────────
        recs: dict[str, object] = {
            r.date: r
            for r in self.services.month_records(f"{y}-{m:02d}")
        }

        total_h = total_ot = 0.0
        workdays = 0
        leave_counts = {k: 0 for k in (
            "paid_leave", "comp_leave", "sick_leave")}
        day_counts = {k: 0 for k in ("normal", "remote", "business_trip")}
        weekly: dict[int, float] = {}
        hover_border = THEMES[self.theme][self.dark][1]
        show_note_markers = self.store.state.show_note_markers

        for d in range(1, days + 1):
            dt = date(y, m, d)
            row = (d + first - 1) // 7
            col = (d + first - 1) % 7
            rec = recs.get(dt.isoformat())   # O(1) dict lookup — no DB call
            h = ot = 0.0
            wt = "normal"
            note_text = ""
            has_pending_note = False
            holiday_note = str(self.holidays.get(dt, "")).strip()
            if rec:
                note_text = rec.safe_note().strip()
                has_pending_note = (
                    bool(note_text)
                    and not rec.has_times
                    and note_text != holiday_note
                )
                h = calc_hours(rec.start, rec.end, rec.break_hours)
                ot = max(h - self.work_hours, 0)
                wt = rec.safe_work_type()
                if h > 0:
                    total_h += h
                    total_ot += ot
                    workdays += 1
                    weekly[row] = weekly.get(row, 0.0) + h
                    if wt in day_counts:
                        day_counts[wt] += 1
                if rec.is_leave:
                    leave_counts[wt] += 1

            lines = [str(d)]
            if dt in self.holidays:
                lines.append(self.holidays[dt])
            if h > 0:
                lines.append(f"{h:.1f}{t['h_unit']}")
            if ot > 0:
                lines.append(f"{t['ot_prefix']}{ot:.1f}{t['h_unit']}")
            abbr = t["wt_abbr"].get(wt, "")
            if abbr:
                lines.append(abbr)

            btn = CalendarDayButton("\n".join(lines))
            btn.setMinimumHeight(86)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            bg, fg, bdr_c, bdr_w = self._cell_style(dt)
            wt_acc = WT_BORDER_ACCENT[self.dark].get(wt)
            if wt_acc:
                btn.setStyleSheet(
                    f"QPushButton{{background-color:{bg};color:{fg};"
                    f"border:2px solid {bdr_c};border-left:4px solid {wt_acc};"
                    f"border-radius:6px;font-size:11px;text-align:center;padding:2px;}}"
                    f"QPushButton:hover{{border:2px solid {hover_border};"
                    f"border-left:4px solid {wt_acc};}}")
            else:
                btn.setStyleSheet(
                    f"QPushButton{{background-color:{bg};color:{fg};"
                    f"border:2px solid {bdr_c};border-radius:6px;"
                    f"font-size:11px;text-align:center;padding:2px;}}"
                    f"QPushButton:hover{{border:2px solid {hover_border};}}")
            show_pending_note = show_note_markers and has_pending_note
            btn.set_note_marker(show_pending_note, hover_border)
            if show_pending_note:
                btn.setToolTip(note_text[:200])
            else:
                btn.setToolTip("")
            btn.clicked.connect(lambda _, x=dt: self.select(x))
            self.grid.addWidget(btn, row + 1, col)
            self._day_btns.append(btn)

        max_row = (days + first - 1) // 7
        for r in range(max_row + 1):
            wh = weekly.get(r, 0.0)
            lbl = QLabel(f"{wh:.1f}{t['h_unit']}" if wh > 0 else "—")
            lbl.setObjectName("week_total_lbl")
            lbl.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(lbl, r + 1, 7)
            self._week_totals.append(lbl)

        leave_total = sum(leave_counts.values())
        avg_h = total_h / workdays if workdays else 0.0
        self.sv_total.setText(f"{total_h:.1f}{t['h_unit']}")
        self.sv_ot.setText(f"{total_ot:.1f}{t['h_unit']}")
        self.sv_avg.setText(f"{avg_h:.1f}{t['h_unit']}")
        self.sv_days.setText(f"{workdays}{t['d_unit']}")
        self.sv_leave.setText(f"{leave_total}{t['d_unit']}")

        self.sv_leave.setToolTip(t["leave_tooltip"].format(
            paid=f"{leave_counts['paid_leave']}{t['d_unit']}",
            comp=f"{leave_counts['comp_leave']}{t['d_unit']}",
            sick=f"{leave_counts['sick_leave']}{t['d_unit']}"))
        self.sv_days.setToolTip(t["days_tooltip"].format(
            normal=f"{day_counts['normal']}{t['d_unit']}",
            remote=f"{day_counts['remote']}{t['d_unit']}",
            biz=f"{day_counts['business_trip']}{t['d_unit']}"))

    def load(self):
        rec = self.services.get_record(self.selected.isoformat())
        def_break = self._safe_float_setting("default_break", 1.0)
        if rec:
            start_val = rec.start or ""
            end_val   = rec.end or ""
            break_val = rec.break_hours if rec.break_hours is not None else def_break
            self.manual_start_in.setText(start_val)
            self.manual_end_in.setText(end_val)
            self.manual_break_in.setText(str(break_val))
            self._auto_start_time = start_val
            self._auto_end_time   = end_val
            self._auto_break_hours = float(break_val)
            self._auto_break_recorded = bool(
                start_val or end_val or float(break_val) > 0)
            self.note_in.setPlainText(rec.safe_note())
            wt = rec.safe_work_type()
            idx = self.wt_combo.findData(wt)
            if idx >= 0:
                self.wt_combo.setCurrentIndex(idx)
        else:
            self.manual_start_in.clear()
            self.manual_end_in.clear()
            self.manual_break_in.setText(str(def_break))
            self.note_in.clear()
            self._auto_start_time  = ""
            self._auto_end_time    = ""
            self._auto_break_hours = def_break
            self._auto_break_recorded = False
            idx = self.wt_combo.findData("normal")
            if idx >= 0:
                self.wt_combo.setCurrentIndex(idx)
        if self.selected in self.holidays and not self.note_in.toPlainText():
            self.note_in.setPlainText(self.holidays[self.selected])
        self._refresh_auto_time_labels()
        self._update_banner()

    def _is_dirty(self) -> bool:
        rec = self.services.get_record(self.selected.isoformat())
        dl = self._safe_float_setting("default_break", 1.0)
        holiday_note = str(self.holidays.get(self.selected, "")).strip()

        s_txt, e_txt, l_cur = self._active_time_values()
        s_cur = parse_time(s_txt) if s_txt else None
        e_cur = parse_time(e_txt) if e_txt else None

        note_cur = self.note_in.toPlainText()
        wt_cur   = self.wt_combo.currentData() or "normal"

        if rec:
            saved_note = rec.safe_note()
            if holiday_note and saved_note == holiday_note:
                saved_note = ""
            if holiday_note and note_cur == holiday_note:
                note_cur = ""
            saved = (rec.start, rec.end,
                     rec.break_hours if rec.break_hours is not None else dl,
                     saved_note,
                     rec.safe_work_type())
        else:
            saved = (None, None, dl, "", "normal")
            if holiday_note and note_cur == holiday_note:
                note_cur = ""
        return (s_cur, e_cur, l_cur, note_cur, wt_cur) != saved

    def save(self):
        s_txt, e_txt, l = self._active_time_values()
        s = parse_time(s_txt) if s_txt else None
        e = parse_time(e_txt) if e_txt else None
        if s_txt and not s:
            if self._time_mode() == "manual":
                self.manual_start_in.setStyleSheet(
                    "QLineEdit{border:2px solid #e03333;}")
            return
        elif self._time_mode() == "manual":
            self.manual_start_in.setStyleSheet("")
        if e_txt and not e:
            if self._time_mode() == "manual":
                self.manual_end_in.setStyleSheet(
                    "QLineEdit{border:2px solid #e03333;}")
            return
        elif self._time_mode() == "manual":
            self.manual_end_in.setStyleSheet("")
        wt = self.wt_combo.currentData() or "normal"
        if self._time_mode() == "manual":
            if s:
                self.manual_start_in.setText(s)
            if e:
                self.manual_end_in.setText(e)
            self._auto_start_time = s or ""
            self._auto_end_time = e or ""
            self._auto_break_hours = l
            self._auto_break_recorded = bool(s or e or l > 0)
        else:
            self._auto_start_time = s or ""
            self._auto_end_time = e or ""
            self._auto_break_hours = l
            self._auto_break_recorded = bool(s or e or l > 0)
            self.manual_start_in.setText(s or "")
            self.manual_end_in.setText(e or "")
            self.manual_break_in.setText(str(l))
        self.services.save_record(self.selected.isoformat(), s, e, l,
                     self.note_in.toPlainText(), wt)
        self._refresh_auto_time_labels()
        self.render()

    def select(self, d: date):
        t = T[self.lang]
        if d != self.selected and self._is_dirty():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(t["confirm_title"])
            box.setText(t["unsaved_msg"])
            box.setStandardButtons(
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Save)
            _localize_msgbox_buttons(box, t)
            ans = box.exec()
            if ans == QMessageBox.Save:
                self.save()
            elif ans == QMessageBox.Cancel:
                return
        self.selected = d
        self.load()
        self.render()

    def go_today(self):
        self.current = self.today.replace(day=1)
        self.selected = self.today
        self.load()
        self.render()

    def prev_m(self):
        m = self.current.month - 1 or 12
        y = self.current.year - (1 if self.current.month == 1 else 0)
        self.current = date(y, m, 1)
        self.render()

    def next_m(self):
        m = self.current.month % 12 + 1
        y = self.current.year + (1 if self.current.month == 12 else 0)
        self.current = date(y, m, 1)
        self.render()

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if mods == Qt.ControlModifier:
            if key == Qt.Key_S:
                self.save()
                return
            if key == Qt.Key_Left:
                self.prev_m()
                return
            if key == Qt.Key_Right:
                self.next_m()
                return
            if key == Qt.Key_T:
                self.go_today()
                return
        if mods == Qt.NoModifier:
            d = self.selected
            if key == Qt.Key_Left:
                prev = (date(d.year, d.month, d.day - 1) if d.day > 1
                        else date(d.year - 1 if d.month == 1 else d.year,
                                  d.month - 1 if d.month > 1 else 12,
                                  monthrange(d.year-1 if d.month == 1 else d.year,
                                             d.month-1 if d.month > 1 else 12)[1]))
                if prev.month != self.current.month:
                    self.current = prev.replace(day=1)
                self.select(prev)
                return
            if key == Qt.Key_Right:
                _, last = monthrange(d.year, d.month)
                nxt = (date(d.year, d.month, d.day + 1) if d.day < last
                       else date(d.year + 1 if d.month == 12 else d.year,
                                 d.month % 12 + 1, 1))
                if nxt.month != self.current.month:
                    self.current = nxt.replace(day=1)
                self.select(nxt)
                return
        super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            if self.isMinimized() and self._residency_enabled() and QSystemTrayIcon.isSystemTrayAvailable():
                QTimer.singleShot(0, self.hide)

    def open_settings(self):
        dlg = SettingsDialog(self, self)
        dlg._export_csv_btn.clicked.connect(self._export_csv)
        dlg._import_csv_btn.clicked.connect(self._import_csv)
        dlg._ics_import_btn.clicked.connect(self._import_ics)
        dlg._ics_export_btn.clicked.connect(self._export_ics)
        dlg._ics_clear_btn.clicked.connect(self._clear_calendar)
        dlg.exec()

    def open_report(self):
        ReportDialog(self, self).exec()

    def open_chart(self):
        ChartDialog(self, self).exec()

    def open_note_editor(self):
        NoteEditorDialog(self, self).exec()

    def _export_csv(self):
        t = T[self.lang]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, t["export_csv"], f"worklog_{ts}.csv", "CSV (*.csv)")
        if not path:
            return
        data = self.services.all_records()
        self.services.export_csv_file(path, data)
        QMessageBox.information(self, t["export_csv"],
                                t["export_saved"].format(path))

    def _import_csv(self):
        t = T[self.lang]
        path, _ = QFileDialog.getOpenFileName(
            self, t["import_csv"], "", "CSV (*.csv)")
        if not path:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(t["confirm_title"])
        box.setText(t["confirm_msg"])
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _localize_msgbox_buttons(box, t)
        if box.exec() != QMessageBox.Yes:
            return
        try:
            n, errors = self.services.import_csv_file(
                path, REQUIRED_COLS,
                default_break=self._safe_float_setting("default_break", 1.0),
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "empty":
                QMessageBox.warning(
                    self, t["import_result"], t["import_empty"])
            elif msg.startswith("missing:"):
                QMessageBox.warning(self, t["import_result"],
                                    t["import_bad"].format(msg[8:]))
            else:
                QMessageBox.critical(self, t["import_result"], msg)
            return
        msg = t["import_ok"].format(n)
        if errors:
            msg += t["import_skip"].format(len(errors), "\n".join(errors[:10]))
        QMessageBox.information(self, t["import_result"], msg)
        self.render()

    def _import_ics(self):
        t = T[self.lang]
        path, _ = QFileDialog.getOpenFileName(
            self, t["ics_import"], "", "iCalendar (*.ics)")
        if not path:
            return
        try:
            rich_events = self.services.parse_calendar_file(path)
            if not rich_events:
                QMessageBox.information(self, t["ics_import"],
                                        t.get("ics_empty", "No events found."))
                return

            # Ask whether to replace or append when calendar data already exists.
            existing_count = len(
                self.services.get_calendar_events_for_range("0000-01-01", "9999-12-31"))
            if existing_count > 0:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle(t["ics_import"])
                box.setText(t.get(
                    "ics_overwrite_confirm",
                    "Calendar data already exists.\n\n"
                    "Replace — clear all previous calendar events before import.\n"
                    "Append — keep existing events and add new ones."))
                replace_btn = box.addButton(
                    t.get("ics_replace_btn", "Replace"),
                    QMessageBox.ButtonRole.DestructiveRole)
                append_btn = box.addButton(
                    t.get("ics_append_btn", "Append"),
                    QMessageBox.ButtonRole.AcceptRole)
                cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
                _localize_msgbox_buttons(box, t)
                box.setDefaultButton(append_btn)
                box.exec()
                clicked = box.clickedButton()
                if clicked == cancel_btn or clicked is None:
                    return
                if clicked == replace_btn:
                    self.services.clear_calendar_events()

            saved = self.services.save_calendar_events(rich_events, source_file=path)
            imported = 0
            for ev in rich_events:
                d_obj = ev.get("date")
                summary = ev.get("summary", "")
                if not d_obj or not summary:
                    continue
                d_str = (d_obj.isoformat()
                         if hasattr(d_obj, "isoformat") else str(d_obj))
                rec = self.services.get_record(d_str)
                if rec:
                    existing_note = rec.safe_note()
                    # Avoid duplicating the same summary on repeated import.
                    if summary not in existing_note:
                        merged = (existing_note + " / " + summary).strip(
                        ) if existing_note else summary
                        self.services.save_record(
                            d_str, rec.start, rec.end, rec.break_hours,
                            merged, rec.safe_work_type())
                else:
                    self.services.save_record(d_str, None, None, 1.0, summary, "normal")
                imported += 1
            QMessageBox.information(
                self, t["ics_import"],
                t.get("cal_imported", t["ics_import_ok"]).format(saved))
            self.render()
        except Exception as ex:
            QMessageBox.critical(self, t["ics_import"], str(ex))

    def _export_ics(self):
        t = T[self.lang]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, t["ics_export"], f"worklog_{ts}.ics", "iCalendar (*.ics)")
        if not path:
            return
        try:
            data = self.services.month_records(self.current.strftime("%Y-%m"))
            content = self.services.export_month_ics(self.current.strftime("%Y-%m"))
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, t["ics_export"],
                                    t["ics_export_ok"].format(len(data)))
        except Exception as ex:
            QMessageBox.critical(self, t["ics_export"], str(ex))

    def open_quick_log(self):
        QuickLogDialog(self, self).exec()

    def _clear_calendar(self):
        t = T[self.lang]
        self.services.clear_calendar_events()
        QMessageBox.information(self, t["cal_section"], t["cal_cleared"])

    def closeEvent(self, e):
        if self._tray_quit_requested:
            e.accept()
            return
        if self._residency_enabled() and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            e.ignore()
            return
        e.accept()
