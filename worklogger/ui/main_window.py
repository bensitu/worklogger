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
from PySide6.QtCore import QRectF, Qt, QTimer, Slot, QEvent
from PySide6.QtGui import QColor, QPainter, QAction

from utils.i18n import _, msg, LANG_NAMES
from config.themes import (
    DEFAULT_CUSTOM_COLOR,
    THEMES,
    THEME_KEYS,
    WT_BORDER_ACCENT,
    auto_break_active_qss,
    calendar_cell_qss,
    cell_pool,
    line_edit_error_qss,
    make_qss,
    set_custom_theme,
    theme_colors,
)
from config.themes import CALENDAR_STYLE
from config.constants import (
    CUSTOM_THEME_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_SETTING_KEY,
    LEGACY_DEFAULT_BREAK_SETTING_KEY,
    LANG_SETTING_KEY,
    MAX_SHIFT_HOURS,
    MAX_SHIFT_HOURS_SETTING_KEY,
    MINIMAL_DATE_NAV_BUTTON_SIZE,
    MINIMAL_DATE_NAV_FEEDBACK_MS,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    THEME_SETTING_KEY,
    TIME_INPUT_MODE_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
    WORK_HOURS_SETTING_KEY,
    WORK_TYPE_KEYS,
)
from core.time_calc import calc_hours, calc_shift_span_hours, is_overnight_shift, detect_country
from core.validator import parse_time
from services.app_services import AppServices
from services.language_manager import get_language_manager
from stores.app_store import AppStore, AppState
from ui.dialogs import (
    SettingsDialog, NoteEditorDialog, ReportDialog, ChartDialog,
    QuickLogDialog,
)
from ui.dialogs.common import _localize_msgbox_buttons
from utils.icon import make_icon

STYLE_PRIO = ["weekend", "today", "holiday", "selected"]
REQUIRED_COLS = {"date", "start", "end", "break", "note"}
ThemeColors = tuple[str, str, str, str, str]
ThemePalette = dict[bool, ThemeColors]
ThemeMap = dict[str, ThemePalette]


class CalendarDayButton(QPushButton):
    """Calendar cell button with optional painted calendar markers."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._show_note_marker = False
        self._marker_color = CALENDAR_STYLE["note_marker_default"]
        self._work_type_marker_color: str | None = None
        self._show_overnight_marker = False
        self._overnight_marker_color = CALENDAR_STYLE["overnight_marker_default"]

    def set_note_marker(self, visible: bool, color: str) -> None:
        self._show_note_marker = visible
        self._marker_color = color
        self.update()

    def set_work_type_marker(self, color: str | None) -> None:
        self._work_type_marker_color = color
        self.update()

    def set_overnight_marker(self, visible: bool, color: str) -> None:
        self._show_overnight_marker = visible
        self._overnight_marker_color = color
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._work_type_marker_color:
            margin = float(CALENDAR_STYLE["work_type_marker_margin"])
            width = float(CALENDAR_STYLE["work_type_marker_width"])
            radius = float(CALENDAR_STYLE["work_type_marker_radius"])
            rect = QRectF(
                margin,
                margin,
                width,
                max(0.0, self.height() - margin * 2),
            )
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._work_type_marker_color))
            p.drawRoundedRect(rect, radius, radius)
        if self._show_note_marker:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(self._marker_color))
            note_size = int(CALENDAR_STYLE["note_marker_size"])
            note_y = int(CALENDAR_STYLE["note_marker_margin"])
            note_x = int(CALENDAR_STYLE["note_marker_margin"])
            if self._work_type_marker_color:
                note_x = int(
                    float(CALENDAR_STYLE["work_type_marker_margin"])
                    + float(CALENDAR_STYLE["work_type_marker_width"])
                    + float(CALENDAR_STYLE["note_marker_work_type_gap"])
                )
            p.drawEllipse(note_x, note_y, note_size, note_size)
        if self._show_overnight_marker:
            p.setPen(QColor(self._overnight_marker_color))
            icon_size = int(CALENDAR_STYLE["overnight_icon_size"])
            icon_margin = int(CALENDAR_STYLE["overnight_icon_margin"])
            x = self.width() - icon_size - icon_margin
            y = icon_margin
            p.drawText(
                x, y,
                icon_size, icon_size,
                Qt.AlignCenter,
                str(CALENDAR_STYLE["overnight_icon"]),
            )
        p.end()


class App(QWidget):
    def __init__(self, services: AppServices | None = None, initial_lang: str | None = None):
        super().__init__()
        self.services = services or AppServices()
        self.language_manager = get_language_manager()
        if services is None:
            self.services.ensure_default_user_session()
        custom_color = set_custom_theme(
            self.services.get_setting(CUSTOM_THEME_SETTING_KEY, DEFAULT_CUSTOM_COLOR)
        )
        self.themes: ThemeMap = {name: dict(palette) for name, palette in THEMES.items()}
        self.today = date.today()
        self.current = self.today.replace(day=1)
        self.selected = self.today

        # Ensure missing settings get safe defaults on first run or upgrade.
        if self.services.get_setting(WORK_HOURS_SETTING_KEY) is None:
            self.services.set_setting(WORK_HOURS_SETTING_KEY, "8.0")
        legacy_default_break = self.services.get_setting(LEGACY_DEFAULT_BREAK_SETTING_KEY)
        if self.services.get_setting(DEFAULT_BREAK_SETTING_KEY) is None:
            self.services.set_setting(DEFAULT_BREAK_SETTING_KEY, legacy_default_break or "1.0")
        if self.services.get_setting(MONTHLY_TARGET_SETTING_KEY) is None:
            self.services.set_setting(MONTHLY_TARGET_SETTING_KEY, str(round(8.0 * 21, 1)))
        if self.services.get_setting(SHOW_HOLIDAYS_SETTING_KEY) is None:
            self.services.set_setting(SHOW_HOLIDAYS_SETTING_KEY, "1")
        if self.services.get_setting(SHOW_NOTE_MARKERS_SETTING_KEY) is None:
            self.services.set_setting(SHOW_NOTE_MARKERS_SETTING_KEY, "1")
        if self.services.get_setting(SHOW_OVERNIGHT_INDICATOR_SETTING_KEY) is None:
            self.services.set_setting(SHOW_OVERNIGHT_INDICATOR_SETTING_KEY, "1")
        residency_key = self._residency_setting_key()
        if residency_key and self.services.get_setting(residency_key) is None:
            self.services.set_setting(residency_key, "0")

        # AppStore is the single source of truth for persisted settings.
        # All code that previously read self.lang / self.theme / self.dark /
        # self.work_hours should use self._state.<field> instead.
        saved_lang = initial_lang or self.services.get_setting(LANG_SETTING_KEY, "en_US")
        saved_theme = self.services.get_setting(THEME_SETTING_KEY, "blue")
        _def_break = self._safe_float_setting(DEFAULT_BREAK_SETTING_KEY, 1.0)
        self.store = AppStore(AppState(
            lang=saved_lang if saved_lang in LANG_NAMES else "en_US",
            theme=saved_theme if saved_theme in THEME_KEYS else "blue",
            custom_color=custom_color,
            dark=self.services.get_setting(DARK_MODE_SETTING_KEY, "0") == "1",
            work_hours=self._safe_float_setting(WORK_HOURS_SETTING_KEY, 8.0),
            default_break=_def_break,
            monthly_target=self._safe_float_setting(
                MONTHLY_TARGET_SETTING_KEY,
                self._safe_float_setting(WORK_HOURS_SETTING_KEY, 8.0) * 21,
            ),
            show_holidays=self.services.get_setting(SHOW_HOLIDAYS_SETTING_KEY, "1") == "1",
            show_note_markers=self.services.get_setting(SHOW_NOTE_MARKERS_SETTING_KEY, "1") == "1",
            show_overnight_indicator=self.services.get_setting(SHOW_OVERNIGHT_INDICATOR_SETTING_KEY, "1") == "1",
            week_start_monday=self.services.get_setting(WEEK_START_MONDAY_SETTING_KEY, "0") == "1",
            time_input_mode=self.services.get_setting(TIME_INPUT_MODE_SETTING_KEY, "manual"),
            minimal_mode=self.services.get_setting(MINIMAL_MODE_SETTING_KEY, "0") == "1",
            current_user_id=self.services.current_user_id,
            current_username=self.services.current_username,
        ))
        self.language_manager.apply(self._state.lang)

        self.holidays: dict = {}
        self._holidays_pending: dict = {}
        self._country = detect_country()
        self._day_btns:    list[QPushButton] = []
        self._week_totals: list[QLabel] = []
        self._break_start: datetime | None = None
        self._break_timer: QTimer | None = None
        self._settings_dialog: SettingsDialog | None = None
        self._active_time_tab = self._state.time_input_mode
        self._auto_start_time = ""
        self._auto_end_time = ""
        self._auto_break_hours = _def_break
        self._auto_break_recorded = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_quit_requested = False

        self._build_ui()
        self._setup_residency_icon()
        self.apply_theme()
        self.apply_lang()
        self.load()
        self.render()

        if not self._state.minimal_mode:
            QTimer.singleShot(0, self._load_holidays)

    def _safe_float_setting(self, key: str, default: float) -> float:
        """Read a float setting with a safe fallback for missing/bad values."""
        try:
            raw = self.services.get_setting(key, str(default))
            if raw is None:
                return default
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _load_holidays(self):
        """Load holiday data in a background thread to avoid blocking UI.
        Uses a QTimer on the main thread to safely marshal the result back.
        """
        if (
            self.store.state.minimal_mode
            or self.services.get_setting(SHOW_HOLIDAYS_SETTING_KEY, "1") == "0"
        ):
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
        self._calendar_panel = left
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
        self._sidebar = sidebar
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(326)
        sv = QVBoxLayout(sidebar)
        sv.setContentsMargins(16, 16, 16, 14)
        sv.setSpacing(8)

        date_nav = QHBoxLayout()
        date_nav.setContentsMargins(0, 0, 0, 0)
        date_nav.setSpacing(6)
        self._minimal_prev_day_btn = QPushButton("◀")
        self._minimal_prev_day_btn.setObjectName("date_nav_btn")
        self._minimal_prev_day_btn.setFixedSize(
            MINIMAL_DATE_NAV_BUTTON_SIZE,
            MINIMAL_DATE_NAV_BUTTON_SIZE,
        )
        self._minimal_prev_day_btn.setToolTip(msg("previous_day"))
        self.date_banner = QLabel()
        self.date_banner.setObjectName("date_banner")
        self.date_banner.setAlignment(Qt.AlignCenter)
        self._minimal_next_day_btn = QPushButton("▶")
        self._minimal_next_day_btn.setObjectName("date_nav_btn")
        self._minimal_next_day_btn.setFixedSize(
            MINIMAL_DATE_NAV_BUTTON_SIZE,
            MINIMAL_DATE_NAV_BUTTON_SIZE,
        )
        self._minimal_next_day_btn.setToolTip(msg("next_day"))
        date_nav.addWidget(self._minimal_prev_day_btn)
        date_nav.addWidget(self.date_banner, 1)
        date_nav.addWidget(self._minimal_next_day_btn)
        sv.addLayout(date_nav)
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
            btn.setMinimumSize(64, 64)
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
        self._stats_divider = self._div()
        sv.addWidget(self._stats_divider)

        stat_card = QFrame()
        self._stats_card = stat_card
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

        analytics_row = QWidget()
        self._analytics_row = analytics_row
        act_row = QHBoxLayout(analytics_row)
        act_row.setContentsMargins(0, 0, 0, 0)
        act_row.setSpacing(6)
        self.report_btn = QPushButton()
        self.report_btn.setObjectName("action_btn")
        self.chart_btn = QPushButton()
        self.chart_btn.setObjectName("action_btn")
        act_row.addWidget(self.report_btn)
        act_row.addWidget(self.chart_btn)
        sv.addWidget(analytics_row)
        sv.addStretch()

        root.addWidget(left, 1)
        root.addWidget(sidebar)
        self._apply_minimal_mode_layout()

        self.prev_btn.clicked.connect(self.prev_m)
        self.next_btn.clicked.connect(self.next_m)
        self.today_btn.clicked.connect(self.go_today)
        self._minimal_prev_day_btn.clicked.connect(lambda: self._shift_minimal_day(-1))
        self._minimal_next_day_btn.clicked.connect(lambda: self._shift_minimal_day(1))
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

    def _apply_minimal_mode_layout(self) -> None:
        minimal = self.store.state.minimal_mode
        self._calendar_panel.setVisible(not minimal)
        self._stats_divider.setVisible(not minimal)
        self._stats_card.setVisible(not minimal)
        self._analytics_row.setVisible(not minimal)
        self._minimal_prev_day_btn.setVisible(minimal)
        self._minimal_next_day_btn.setVisible(minimal)
        self._update_minimal_date_nav()
        if minimal:
            self._fit_minimal_window()
        else:
            self.setMinimumSize(900, 580)

    def _fit_minimal_window(self) -> None:
        self._sidebar.adjustSize()
        hint = self._sidebar.sizeHint()
        width = max(340, hint.width() + 18)
        height = max(450, hint.height() + 28)
        self.setMinimumSize(width, height)
        self.resize(width, height)
        self.adjustSize()

    @property
    def _state(self):
        """Single source of truth for all persisted settings.

        Replaces the former ``self.lang`` / ``self.theme`` / ``self.dark`` /
        ``self.work_hours`` instance variables.  Always read settings through
        here; write via ``self.store.patch()``.
        """
        return self.store.state

    # Compatibility shims for callers that still assign app.* settings directly.
    # SettingsDialog still writes ``app.lang = …`` / ``app.dark = …`` etc.
    # These properties route those assignments through AppStore so the store
    # remains the single source of truth.

    @property
    def lang(self) -> str:
        return self._state.lang

    @lang.setter
    def lang(self, value: str) -> None:
        result = self.language_manager.apply(value)
        self.store.patch(lang=result.language)

    @property
    def theme(self) -> str:
        return self._state.theme

    @theme.setter
    def theme(self, value: str) -> None:
        self.store.patch(theme=value)

    @property
    def dark(self) -> bool:
        return self._state.dark

    @dark.setter
    def dark(self, value: bool) -> None:
        self.store.patch(dark=value)

    @property
    def work_hours(self) -> float:
        return self._state.work_hours

    @work_hours.setter
    def work_hours(self, value: float) -> None:
        self.store.patch(work_hours=value)

    @property
    def current_user_id(self) -> int | None:
        return self.services.current_user_id

    @property
    def current_username(self) -> str | None:
        return self.services.current_username

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
        self._tray_open_action.setText(_("Open"))
        self._tray_quick_log_action.setText(_("Quick Log"))
        self._tray_quit_action.setText(_("Quit"))
        self._tray_icon.setToolTip(_("Work Logger"))
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
        self.setWindowTitle(_("Work Logger"))
        self.time_tabs.setTabText(0, _("Manual Input"))
        self.time_tabs.setTabText(1, _("Auto Record"))
        self.manual_lbl_start.setText(_("Start"))
        self.manual_lbl_end.setText(_("End"))
        self.manual_lbl_break.setText(_("Break (h)"))
        self.manual_start_in.setPlaceholderText(
            _("HH:MM"))
        self.manual_end_in.setPlaceholderText(
            _("HH:MM"))
        self.manual_break_in.setPlaceholderText(
            _("1.0"))
        self.auto_lbl_start.setText(_("Start"))
        self.auto_lbl_end.setText(_("End"))
        self.auto_lbl_break.setText(_("Break (h)"))
        self.lbl_wt.setText(_("Work type"))
        self.lbl_note.setText(_("Notes"))
        self.clock_in_btn.setText(msg("start_now", _("Start")))
        self.clock_out_btn.setText(msg("end_now", _("End")))
        self.save_btn.setText(_("Save"))
        self.settings_btn.setText(_("⚙  Settings"))
        self.report_btn.setText(_("Report"))
        self.chart_btn.setText(_("Analytics"))
        self.quick_log_btn.setText(_("⚡ Quick Log"))
        self.prev_btn.setToolTip(_("Previous month"))
        self.next_btn.setToolTip(_("Next month"))
        self.today_btn.setToolTip(_("Today"))
        self._minimal_prev_day_btn.setToolTip(msg("previous_day"))
        self._minimal_next_day_btn.setToolTip(msg("next_day"))
        self.note_expand_btn.setToolTip(_("Expand notes"))
        week_start_monday = self.services.get_setting(WEEK_START_MONDAY_SETTING_KEY, "0") == "1"
        days_list = list([_("Sun"), _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat")])
        if week_start_monday:
            days_list = days_list[1:] + days_list[:1]
        for i, lbl in enumerate(self.week_day_lbls):
            lbl.setText(days_list[i])
        self.week_col_hdr.setText(_("Total"))
        self.sk_total.setText(_("Monthly total"))
        self.sk_ot.setText(_("Overtime"))
        self.sk_avg.setText(_("Daily avg"))
        self.sk_days.setText(_("Work days"))
        self.sk_leave.setText(_("Leave days"))
        self._refresh_auto_time_labels()
        self._update_residency_state()
        cur_wt = self.wt_combo.currentData() or "normal"
        self.wt_combo.blockSignals(True)
        self.wt_combo.clear()
        wk = {
            "normal": _("Normal"),
            "remote": _("Remote work"),
            "business_trip": _("Business trip"),
            "paid_leave": _("Paid leave"),
            "comp_leave": _("Comp leave"),
            "sick_leave": _("Sick leave"),
        }
        for key in WORK_TYPE_KEYS:
            self.wt_combo.addItem(wk.get(key, key), key)
        idx = self.wt_combo.findData(cur_wt)
        if idx >= 0:
            self.wt_combo.setCurrentIndex(idx)
        self.wt_combo.blockSignals(False)
        self._update_banner()

    def _update_banner(self):
        d = self.selected
        week_start_monday = self.services.get_setting(WEEK_START_MONDAY_SETTING_KEY, "0") == "1"
        if week_start_monday:
            dow = [_("Sun"), _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat")][d.weekday()]
        else:
            dow = [_("Sun"), _("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat")][(d.weekday() + 1) % 7]
        overnight = False
        rec = self.services.get_record(d.isoformat())
        if rec and rec.is_overnight:
            overnight = True
        else:
            s_txt, e_txt, break_val = self._active_time_values()
            s = parse_time(s_txt) if s_txt else None
            e = parse_time(e_txt) if e_txt else None
            if s and e and is_overnight_shift(s, e):
                overnight = True
        marker = f"  {_("Overnight")}" if overnight else ""
        self.date_banner.setText(f"{d.year}/{d.month:02d}/{d.day:02d}  {dow}{marker}")
        self._update_minimal_date_nav()

    def _update_minimal_date_nav(self) -> None:
        if not hasattr(self, "_minimal_prev_day_btn"):
            return
        if not self.store.state.minimal_mode:
            return
        self._minimal_prev_day_btn.setEnabled(self.selected > date.min)
        self._minimal_next_day_btn.setEnabled(self.selected < date.max)

    def _flash_date_nav_button(self, button: QPushButton) -> None:
        button.setDown(True)
        button.setEnabled(False)
        QTimer.singleShot(MINIMAL_DATE_NAV_FEEDBACK_MS, lambda: self._restore_date_nav_button(button))

    def _restore_date_nav_button(self, button: QPushButton) -> None:
        button.setDown(False)
        self._update_minimal_date_nav()

    def _shift_minimal_day(self, days: int) -> None:
        button = self._minimal_next_day_btn if days > 0 else self._minimal_prev_day_btn
        self._flash_date_nav_button(button)
        try:
            target = self.selected + timedelta(days=days)
        except OverflowError:
            self._update_minimal_date_nav()
            return
        if target == self.selected:
            return
        self.current = target.replace(day=1)
        self.select(target)

    def _time_mode(self) -> str:
        return "auto" if self.time_tabs.currentIndex() == 1 else "manual"

    def _on_time_tab_changed(self, index: int):
        self._active_time_tab = "auto" if index == 1 else "manual"
        self.services.set_setting(TIME_INPUT_MODE_SETTING_KEY, self._active_time_tab)

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
                self._safe_float_setting(DEFAULT_BREAK_SETTING_KEY, 1.0))
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
        self.clock_in_btn.setText(
            f"{_("Started")}\n{self._auto_start_time}"
            if self._auto_start_time else msg("start_now", _("Start"))
        )
        self.clock_out_btn.setText(
            f"{_("Ended")}\n{self._auto_end_time}"
            if self._auto_end_time else msg("end_now", _("End"))
        )
        if self._break_start is None:
            if self._auto_break_recorded:
                self.break_btn.setText(
                    f"{_("Break done")}\n{self._auto_break_hours:.1f}{_("h")}"
                )
            else:
                self.break_btn.setText(_("▶ Break"))

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
                    DEFAULT_BREAK_SETTING_KEY, 1.0)
            except (TypeError, ValueError):
                break_val = self._safe_float_setting(DEFAULT_BREAK_SETTING_KEY, 1.0)
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
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Break Timer"))
        box.setText(_("You already logged {hours}h of break time. What do you want to do?").format(
            hours=f"{self._auto_break_hours:.1f}"))
        restart_btn = box.addButton(
            _("Restart"), QMessageBox.ButtonRole.AcceptRole)
        continue_btn = box.addButton(
            _("Continue"), QMessageBox.ButtonRole.ActionRole)
        cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
        _localize_msgbox_buttons(box, _)
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
        if self._break_start is None:
            return
        mins = (datetime.now() - self._break_start).seconds // 60
        self.break_btn.setText(f"{_("On break")}\n{mins}m")
        self._auto_break_hours = mins / 60
        self.break_btn.setStyleSheet(auto_break_active_qss(self.dark))

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
        if self.store.state.minimal_mode:
            return

        y, m = self.current.year, self.current.month
        self.month_title.setText(f"{y}  {[_("January"), _("February"), _("March"), _("April"), _("May"), _("June"), _("July"), _("August"), _("September"), _("October"), _("November"), _("December")][m-1]}")
        raw_first, days = monthrange(y, m)
        week_start_monday = self.store.state.week_start_monday
        first = raw_first if week_start_monday else (raw_first + 1) % 7

        # Load all month records once and reuse them per calendar cell.
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
        hover_border = theme_colors(self.theme, self.dark)[1]
        show_note_markers = self.store.state.show_note_markers
        show_overnight_indicator = self.store.state.show_overnight_indicator

        for d in range(1, days + 1):
            dt = date(y, m, d)
            row = (d + first - 1) // 7
            col = (d + first - 1) % 7
            rec = recs.get(dt.isoformat())
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
                wt = rec.safe_work_type()
                h = calc_hours(rec.start, rec.end, rec.break_hours) if rec.has_times else 0.0
                ot = 0.0 if rec.is_leave else max(h - self.work_hours, 0)
                if h > 0 and not rec.is_leave:
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
                lines.append(f"{h:.1f}{_('h')}")
            if ot > 0:
                lines.append(f"{_('+')}{ot:.1f}{_('h')}")
            abbr = {'normal': "", 'remote': _("WFH"), 'business_trip': _("Trip"), 'paid_leave': _("PTO"), 'comp_leave': _("CTO"), 'sick_leave': _("Sick")}.get(wt, "")
            if abbr:
                lines.append(abbr)
            btn = CalendarDayButton("\n".join(lines))
            btn.setMinimumHeight(86)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            bg, fg, bdr_c, bdr_w = self._cell_style(dt)
            wt_acc = WT_BORDER_ACCENT[self.dark].get(wt)
            btn.setStyleSheet(
                calendar_cell_qss(bg, fg, bdr_c, hover_border)
            )
            btn.set_work_type_marker(wt_acc)
            show_pending_note = show_note_markers and has_pending_note
            btn.set_note_marker(show_pending_note, hover_border)
            overnight_marker = show_overnight_indicator and bool(rec and rec.is_overnight)
            marker_color = CALENDAR_STYLE["overnight_marker_by_mode"][bool(self.dark)]
            btn.set_overnight_marker(overnight_marker, marker_color)
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
            lbl = QLabel(f"{wh:.1f}{_("h")}" if wh > 0 else "—")
            lbl.setObjectName("week_total_lbl")
            lbl.setAlignment(Qt.AlignCenter)
            self.grid.addWidget(lbl, r + 1, 7)
            self._week_totals.append(lbl)

        leave_total = sum(leave_counts.values())
        avg_h = total_h / workdays if workdays else 0.0
        self.sv_total.setText(f"{total_h:.1f}{_("h")}")
        self.sv_ot.setText(f"{total_ot:.1f}{_("h")}")
        self.sv_avg.setText(f"{avg_h:.1f}{_("h")}")
        self.sv_days.setText(f"{workdays}{_(" days")}")
        self.sv_leave.setText(f"{leave_total}{_(" days")}")

        self.sv_leave.setToolTip(_("Paid: {paid}\nComp: {comp}\nSick: {sick}").format(
            paid=f"{leave_counts['paid_leave']}{_(" days")}",
            comp=f"{leave_counts['comp_leave']}{_(" days")}",
            sick=f"{leave_counts['sick_leave']}{_(" days")}"))
        self.sv_days.setToolTip(_("Normal: {normal}\nRemote: {remote}\nBusiness: {biz}").format(
            normal=f"{day_counts['normal']}{_(" days")}",
            remote=f"{day_counts['remote']}{_(" days")}",
            biz=f"{day_counts['business_trip']}{_(" days")}"))

    def load(self):
        rec = self.services.get_record(self.selected.isoformat())
        def_break = self._safe_float_setting(DEFAULT_BREAK_SETTING_KEY, 1.0)
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
        dl = self._safe_float_setting(DEFAULT_BREAK_SETTING_KEY, 1.0)
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
                self.manual_start_in.setStyleSheet(line_edit_error_qss())
            return
        elif self._time_mode() == "manual":
            self.manual_start_in.setStyleSheet("")
        if e_txt and not e:
            if self._time_mode() == "manual":
                self.manual_end_in.setStyleSheet(line_edit_error_qss())
            return
        elif self._time_mode() == "manual":
            self.manual_end_in.setStyleSheet("")
        if l < 0:
            QMessageBox.warning(
                self,
                _("Confirm"),
                _("Break hours cannot be negative."),
            )
            return
        if s and e:
            max_shift = float(
                self.services.get_setting(
                    MAX_SHIFT_HOURS_SETTING_KEY,
                    str(MAX_SHIFT_HOURS),
                ) or MAX_SHIFT_HOURS
            )
            span_h = calc_shift_span_hours(s, e, max_shift_hours=max_shift)
            if span_h is None:
                if self._time_mode() == "manual":
                    self.manual_end_in.setStyleSheet(line_edit_error_qss())
                QMessageBox.warning(
                    self,
                    _("Confirm"),
                    msg(
                        "shift_span_invalid",
                        "Invalid time range. The shift must be within {max_hours} hours (overnight is supported).",
                    ).format(max_hours=int(max_shift)),
                )
                return
            if l >= span_h:
                QMessageBox.warning(
                    self,
                    _("Confirm"),
                    msg(
                        "break_too_long",
                        "Break time must be less than the total shift duration.",
                    ),
                )
                return
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
        overnight = 1 if (s and e and is_overnight_shift(s, e)) else 0
        self.services.save_record(
            self.selected.isoformat(), s, e, l,
            self.note_in.toPlainText(), wt, overnight=overnight,
        )
        self._refresh_auto_time_labels()
        self.render()

    def select(self, d: date):
        if d != self.selected and self._is_dirty():
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Question)
            box.setWindowTitle(_("Confirm"))
            box.setText(_("Unsaved changes — save before switching?"))
            box.setStandardButtons(
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel
            )
            box.setDefaultButton(QMessageBox.StandardButton.Save)
            _localize_msgbox_buttons(box, _)
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
        self._settings_dialog = dlg
        dlg._export_csv_btn.clicked.connect(self._export_csv)
        dlg._import_csv_btn.clicked.connect(self._import_csv)
        dlg._backup_db_btn.clicked.connect(self._backup_database)
        dlg._restore_db_btn.clicked.connect(self._restore_database)
        dlg._ics_import_btn.clicked.connect(self._import_ics)
        dlg._ics_export_btn.clicked.connect(self._export_ics)
        dlg._ics_clear_btn.clicked.connect(self._clear_calendar)
        dlg.logout_requested.connect(self._on_logout)
        try:
            dlg.exec()
        finally:
            if getattr(self, "_settings_dialog", None) is dlg:
                self._settings_dialog = None

    def _on_logout(self) -> None:
        dlg = getattr(self, "_settings_dialog", None)
        if dlg is not None:
            dlg.close()
        self.services.logout()
        QTimer.singleShot(50, self._restart_to_login)

    def _restart_to_login(self) -> None:
        self.hide()
        from main import authenticate
        if authenticate(self.services) is None:
            self._tray_quit_requested = True
            self.close()
            QApplication.instance().quit()
            return
        self._reload_current_user_state()
        self.show()

    def _reload_current_user_state(self) -> None:
        state = self.services.load_settings()
        self.store.patch(
            lang=state.lang,
            theme=state.theme,
            custom_color=state.custom_color,
            dark=state.dark,
            work_hours=state.work_hours,
            default_break=state.default_break,
            monthly_target=state.monthly_target,
            show_holidays=state.show_holidays,
            show_note_markers=state.show_note_markers,
            show_overnight_indicator=state.show_overnight_indicator,
            week_start_monday=state.week_start_monday,
            time_input_mode=state.time_input_mode,
            minimal_mode=state.minimal_mode,
            current_user_id=self.services.current_user_id,
            current_username=self.services.current_username,
        )
        self._active_time_tab = self._state.time_input_mode
        self.language_manager.apply(self._state.lang)
        self.apply_theme()
        self.apply_lang()
        self.load()
        self.render()

    def open_report(self):
        if self.store.state.minimal_mode:
            return
        ReportDialog(self, self).exec()

    def open_chart(self):
        if self.store.state.minimal_mode:
            return
        ChartDialog(self, self).exec()

    def open_note_editor(self):
        NoteEditorDialog(self, self).exec()

    def _export_csv(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, _("Export CSV"), f"worklog_{ts}.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            data = self.services.all_records()
            self.services.export_csv_file(path, data)
            QMessageBox.information(self, _("Export CSV"),
                                    _("Saved: {}").format(path))
        except OSError as exc:
            QMessageBox.critical(self, _("Export CSV"), str(exc))

    def _data_transfer_error_message(self, exc: Exception) -> str:
        if isinstance(exc, FileNotFoundError):
            return _("The selected file does not exist.")
        if isinstance(exc, ValueError):
            return {
                "backup_same_path": _(
                    "Backup destination must be different from the active database."
                ),
                "restore_integrity_failed": _(
                    "The selected backup database appears to be corrupted."
                ),
                "restore_missing_users": _(
                    "The selected backup does not contain user account data."
                ),
                "restore_user_mismatch": _(
                    "The selected backup does not contain the current account."
                ),
            }.get(str(exc), str(exc))
        return str(exc)

    def _backup_database(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            _("Backup Data"),
            f"worklog_backup_{ts}.db",
            _("SQLite Database (*.db)"),
        )
        if not path:
            return
        try:
            self.services.backup_database(path)
            dlg = getattr(self, "_settings_dialog", None)
            if dlg is not None and hasattr(dlg, "_backup_reminder_lbl"):
                dlg._backup_reminder_lbl.setVisible(False)
            QMessageBox.information(
                self, _("Backup Data"), _("Backup saved: {}").format(path))
        except Exception as exc:
            QMessageBox.critical(
                self, _("Backup Data"), self._data_transfer_error_message(exc))

    def _restore_database(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, _("Restore Data"), "", _("SQLite Database (*.db)"))
        if not path:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(_("Restore Data"))
        box.setText(_("Restore will replace the current database file. Continue?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _localize_msgbox_buttons(box, _)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            if not self.services.restore_database(path):
                QMessageBox.critical(
                    self, _("Restore Data"), _("Restore failed."))
                return
            dlg = getattr(self, "_settings_dialog", None)
            if dlg is not None:
                dlg.close()
            self._reload_current_user_state()
            QMessageBox.information(
                self, _("Restore Data"), _("Data restored successfully."))
        except Exception as exc:
            QMessageBox.critical(
                self, _("Restore Data"), self._data_transfer_error_message(exc))

    def _import_csv(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, _("Import CSV"), "", "CSV (*.csv)")
        if not path:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(_("Confirm"))
        box.setText(_("Overwrite existing data?"))
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        _localize_msgbox_buttons(box, _)
        if box.exec() != QMessageBox.Yes:
            return
        try:
            n, errors = self.services.import_csv_file(
                path, REQUIRED_COLS,
                default_break=self._safe_float_setting(DEFAULT_BREAK_SETTING_KEY, 1.0),
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "empty":
                QMessageBox.warning(
                    self, _("Import Result"), _("CSV file is empty."))
            elif msg.startswith("missing:"):
                QMessageBox.warning(self, _("Import Result"),
                                    _("Missing columns: {}").format(msg[8:]))
            else:
                QMessageBox.critical(self, _("Import Result"), msg)
            return
        msg = _("Imported {} records.").format(n)
        if errors:
            msg += _("\n\nSkipped {} rows:\n{}").format(len(errors), "\n".join(errors[:10]))
        QMessageBox.information(self, _("Import Result"), msg)
        self.render()

    def _import_ics(self):
        path, _selected_filter = QFileDialog.getOpenFileName(
            self, _("Import .ics"), "", "iCalendar (*.ics)")
        if not path:
            return
        try:
            rich_events = self.services.parse_calendar_file(path)
            if not rich_events:
                QMessageBox.information(self, _("Import .ics"),
                                        _("No events found."))
                return

            # Ask whether to replace or append when calendar data already exists.
            existing_count = len(
                self.services.get_calendar_events_for_range("0000-01-01", "9999-12-31"))
            if existing_count > 0:
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Question)
                box.setWindowTitle(_("Import .ics"))
                box.setText(msg(
                    "ics_overwrite_confirm",
                    "Calendar data already exists.\n\n"
                    "Replace — clear all previous calendar events before import.\n"
                    "Append — keep existing events and add new ones."))
                replace_btn = box.addButton(
                    _("Replace"),
                    QMessageBox.ButtonRole.DestructiveRole)
                append_btn = box.addButton(
                    _("Append"),
                    QMessageBox.ButtonRole.AcceptRole)
                cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
                _localize_msgbox_buttons(box, _)
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
                self, _("Import .ics"),
                msg("cal_imported", _("Imported {} calendar events.")).format(saved))
            self.render()
        except Exception as ex:
            QMessageBox.critical(self, _("Import .ics"), str(ex))

    def _export_ics(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _selected_filter = QFileDialog.getSaveFileName(
            self, _("Export .ics"), f"worklog_{ts}.ics", "iCalendar (*.ics)")
        if not path:
            return
        try:
            data = self.services.month_records(self.current.strftime("%Y-%m"))
            content = self.services.export_month_ics(self.current.strftime("%Y-%m"))
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            QMessageBox.information(self, _("Export .ics"),
                                    _("Exported {} events.").format(len(data)))
        except Exception as ex:
            QMessageBox.critical(self, _("Export .ics"), str(ex))

    def open_quick_log(self):
        QuickLogDialog(self, self).exec()

    def _clear_calendar(self):
        self.services.clear_calendar_events()
        QMessageBox.information(self, _("Calendar Sync"), _("Calendar events cleared."))

    def closeEvent(self, e):
        if self._tray_quit_requested:
            e.accept()
            return
        if self._residency_enabled() and QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            e.ignore()
            return
        e.accept()
