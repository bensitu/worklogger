from __future__ import annotations
import sys
import threading
from typing import Any

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QPushButton, QLabel, QLineEdit, QTextEdit, QScrollArea, QMessageBox,
    QDoubleSpinBox, QGroupBox, QDialogButtonBox, QComboBox, QProgressBar,
    QFrame, QFileDialog, QStyle,
)
from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont

from utils.i18n import _, msg, LANG_NAMES, get_translator
from config.constants import (
    APP_AUTHOR,
    APP_VERSION,
    CUSTOM_THEME_SETTING_KEY,
    DARK_MODE_SETTING_KEY,
    DEFAULT_BREAK_SETTING_KEY,
    GITHUB_URL,
    GPL_URL,
    LANG_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
    MINIMAL_MODE_SETTING_KEY,
    MONTHLY_TARGET_SETTING_KEY,
    SHOW_HOLIDAYS_SETTING_KEY,
    SHOW_NOTE_MARKERS_SETTING_KEY,
    SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
    THEME_SETTING_KEY,
    WEEK_START_MONDAY_SETTING_KEY,
    WORK_HOURS_SETTING_KEY,
)
from config.themes import (
    DEFAULT_CUSTOM_COLOR, THEMES, THEME_KEYS, THEME_NAMES,
    normalize_hex_color, set_custom_theme, switch_off_color,
    local_model_download_blocked_qss, status_label_qss, theme_colors,
)
from utils.formatters import parse_status
from ui.widgets import SwitchButton
from .common import _div, _localize_msgbox_buttons

ThemeColors = tuple[str, str, str, str, str]
ThemePalette = dict[bool, ThemeColors]
ThemeMap = dict[str, ThemePalette]


class _LocalVerifyBridge(QObject):
    progress = Signal(int, int)
    done = Signal(int, bool, bool, str, str)


class SettingsDialog(QDialog):
    _session_local_verify_done = False
    _session_local_verify_cache: dict[str, tuple[bool, str]] = {}

    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        self.setWindowTitle(_("Settings"))
        self.setMinimumSize(450, 500)
        self.resize(450, 590)
        self.setModal(True)
        self.setAttribute(Qt.WA_AlwaysShowToolTips, True)

        lv = QVBoxLayout(self)
        tabs = QTabWidget()

        FW = 260

        app_w = QWidget()
        af = QFormLayout(app_w)
        af.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        af.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        af.setSpacing(10)
        af.setContentsMargins(14, 14, 14, 14)

        self._lang_cb = QComboBox()
        self._lang_cb.setFixedWidth(FW)
        for lang_code, lang_name in LANG_NAMES.items():
            self._lang_cb.addItem(lang_name, lang_code)
        idx = self._lang_cb.findData(app_ref.lang)
        if idx >= 0:
            self._lang_cb.setCurrentIndex(idx)
        af.addRow(_("🌍  Language").lstrip("🌍 "), self._lang_cb)

        _acc = theme_colors(app_ref.theme, app_ref.dark)[0]
        _off_col = switch_off_color(app_ref.dark)
        dark_wrap = QWidget()
        dh = QHBoxLayout(dark_wrap)
        dh.setContentsMargins(0, 0, 0, 0)
        self._dark = SwitchButton(checked=app_ref.dark,
                                  color_on=_acc, color_off=_off_col)
        dh.addWidget(self._dark)
        dh.addStretch()
        af.addRow(_("🌙  Dark mode").lstrip("🌙☀ "), dark_wrap)

        self._theme_cb = QComboBox()
        self._theme_cb.setFixedWidth(FW)
        for k in THEME_KEYS:
            self._theme_cb.addItem(_(THEME_NAMES[k]), k)
        idx2 = self._theme_cb.findData(app_ref.theme)
        if idx2 >= 0:
            self._theme_cb.setCurrentIndex(idx2)
        state = getattr(getattr(app_ref, "store", None), "state", None)
        fallback_custom_color = getattr(
            state,
            "custom_color",
            DEFAULT_CUSTOM_COLOR,
        ) or DEFAULT_CUSTOM_COLOR
        self._custom_color = normalize_hex_color(
            app_ref.services.get_setting(
                CUSTOM_THEME_SETTING_KEY,
                fallback_custom_color,
            )
        )
        theme_wrap = QWidget()
        theme_l = QHBoxLayout(theme_wrap)
        theme_l.setContentsMargins(0, 0, 0, 0)
        theme_l.setSpacing(8)
        theme_l.addWidget(self._theme_cb)
        self._custom_color_btn = QPushButton()
        self._custom_color_btn.setFixedSize(32, 28)
        self._custom_color_btn.setText("")
        self._custom_color_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_CommandLink)
        )
        self._custom_color_btn.setIconSize(QSize(18, 18))
        self._custom_color_btn.setToolTip(msg("open_color_picker"))
        self._custom_color_btn.clicked.connect(self._open_custom_color_dialog)
        theme_l.addWidget(self._custom_color_btn)
        theme_l.addStretch()
        self._theme_cb.currentIndexChanged.connect(self._sync_custom_theme_controls)
        af.addRow(_("🎨  Theme").lstrip("🎨 "), theme_wrap)
        self._sync_custom_theme_controls()

        minimal_wrap = QWidget()
        mh = QHBoxLayout(minimal_wrap)
        mh.setContentsMargins(0, 0, 0, 0)
        self._minimal_mode = SwitchButton(
            checked=app_ref.services.get_setting(
                MINIMAL_MODE_SETTING_KEY,
                "0",
            ) == "1",
            color_on=_acc,
            color_off=_off_col,
        )
        self._minimal_mode.toggled.connect(self._on_minimal_mode_toggled)
        mh.addWidget(self._minimal_mode)
        mh.addStretch()
        af.addRow(msg("minimal_mode"), minimal_wrap)
        tabs.addTab(app_w, _("Appearance"))

        gen_w = QWidget()
        gf = QFormLayout(gen_w)
        gf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        gf.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        gf.setSpacing(10)
        gf.setContentsMargins(14, 14, 14, 14)

        self._wh = QDoubleSpinBox()
        self._wh.setFixedWidth(FW)
        self._wh.setRange(1.0, 24.0)
        self._wh.setSingleStep(0.5)
        self._wh.setValue(app_ref.work_hours)
        gf.addRow(_("Standard hours (h)"), self._wh)

        self._dl = QDoubleSpinBox()
        self._dl.setFixedWidth(FW)
        self._dl.setRange(0.0, 4.0)
        self._dl.setSingleStep(0.5)
        self._dl.setValue(app_ref._safe_float_setting(DEFAULT_BREAK_SETTING_KEY, 1.0))
        gf.addRow(_("Default break (h)"), self._dl)

        self._mt = QDoubleSpinBox()
        self._mt.setFixedWidth(FW)
        self._mt.setRange(0.0, 400.0)
        self._mt.setSingleStep(8.0)
        self._mt.setValue(app_ref._safe_float_setting(
            MONTHLY_TARGET_SETTING_KEY, round(app_ref.work_hours * 21, 1)))
        gf.addRow(_("Monthly target (h)"), self._mt)

        _show_hol_on = app_ref.services.get_setting(
            SHOW_HOLIDAYS_SETTING_KEY, "1") == "1"
        show_hol_wrap = QWidget()
        sh = QHBoxLayout(show_hol_wrap)
        sh.setContentsMargins(0, 0, 0, 0)
        self._show_holidays = SwitchButton(checked=_show_hol_on,
                                           color_on=_acc, color_off=_off_col)
        sh.addWidget(self._show_holidays)
        sh.addStretch()
        gf.addRow(_("Public holidays"), show_hol_wrap)

        _show_note_markers_on = app_ref.services.get_setting(
            SHOW_NOTE_MARKERS_SETTING_KEY, "1") == "1"
        show_note_markers_wrap = QWidget()
        sn = QHBoxLayout(show_note_markers_wrap)
        sn.setContentsMargins(0, 0, 0, 0)
        self._show_note_markers = SwitchButton(
            checked=_show_note_markers_on,
            color_on=_acc,
            color_off=_off_col,
        )
        sn.addWidget(self._show_note_markers)
        sn.addStretch()
        gf.addRow(_("Notes reminder dot"), show_note_markers_wrap)

        _show_overnight_on = app_ref.services.get_setting(
            SHOW_OVERNIGHT_INDICATOR_SETTING_KEY, "1") == "1"
        overnight_wrap = QWidget()
        ov = QHBoxLayout(overnight_wrap)
        ov.setContentsMargins(0, 0, 0, 0)
        self._show_overnight_indicator = SwitchButton(
            checked=_show_overnight_on,
            color_on=_acc,
            color_off=_off_col,
        )
        ov.addWidget(self._show_overnight_indicator)
        ov.addStretch()
        gf.addRow(
            _("Overnight indicator"),
            overnight_wrap,
        )

        _week_start_on = app_ref.services.get_setting(
            WEEK_START_MONDAY_SETTING_KEY, "0") == "1"
        week_start_wrap = QWidget()
        ws = QHBoxLayout(week_start_wrap)
        ws.setContentsMargins(0, 0, 0, 0)
        self._week_start_monday = SwitchButton(
            checked=_week_start_on,
            color_on=_acc,
            color_off=_off_col,
        )
        ws.addWidget(self._week_start_monday)
        ws.addStretch()
        gf.addRow(_("Start week on Monday"), week_start_wrap)

        residency_key = "enable_tray" if sys.platform == "win32" else (
            "enable_menu_bar" if sys.platform == "darwin" else ""
        )
        if residency_key:
            residency_wrap = QWidget()
            rs = QHBoxLayout(residency_wrap)
            rs.setContentsMargins(0, 0, 0, 0)
            self._residency_switch = SwitchButton(
                checked=app_ref.services.get_setting(
                    residency_key, "0") == "1",
                color_on=_acc,
                color_off=_off_col,
            )
            rs.addWidget(self._residency_switch)
            rs.addStretch()
            residency_label = "enable_tray" if sys.platform == "win32" else "enable_menu_bar"
            gf.addRow(msg(residency_label), residency_wrap)
        else:
            self._residency_switch = None
            residency_key = ""
        self._residency_key = residency_key

        tabs.addTab(gen_w, _("General"))

        ai_scroll = QScrollArea()
        ai_scroll.setWidgetResizable(True)
        ai_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ai_inner = QWidget()
        ai_scroll.setWidget(ai_inner)
        aiv = QVBoxLayout(ai_inner)
        aiv.setContentsMargins(14, 14, 14, 14)
        aiv.setSpacing(12)

        _acc = theme_colors(app_ref.theme, app_ref.dark)[0]
        _off = switch_off_color(app_ref.dark)

        # External model connection settings.
        grp_ext = QGroupBox(_("External Model"))
        gfl = QFormLayout(grp_ext)
        gfl.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        gfl.setSpacing(8)
        gfl.setContentsMargins(10, 10, 10, 10)

        def _ai_line(placeholder=""):
            le = QLineEdit()
            le.setFixedWidth(FW)
            le.setPlaceholderText(placeholder)
            return le

        self._ai_key = _ai_line(_("sk-… / sk-ant-…"))
        self._ai_key.setEchoMode(QLineEdit.Password)
        self._ai_key.setText("")
        gfl.addRow(_("API Key"), self._ai_key)

        self._ai_url = _ai_line(
            _("https://api.openai.com/v1 | https://api.anthropic.com"))
        self._ai_url.setText("")
        gfl.addRow(_("API Base URL"), self._ai_url)

        self._ai_model = _ai_line(
            _("gpt-4o-mini | claude-haiku-4-5-20251001"))
        self._ai_model.setText("")
        gfl.addRow(_("Model"), self._ai_model)

        def _load_ai_fields_lazily() -> None:
            self._ai_key.setText(app_ref.services.get_secret("ai_api_key"))
            self._ai_url.setText(app_ref.services.get_setting("ai_base_url", ""))
            self._ai_model.setText(app_ref.services.get_setting("ai_model", ""))

        QTimer.singleShot(0, _load_ai_fields_lazily)

        ext_test_row = QHBoxLayout()
        ext_test_row.setSpacing(8)
        self._ai_test_btn = QPushButton(_("Test"))
        self._ai_test_btn.setObjectName("action_btn")
        self._ai_test_btn.setFixedWidth(80)
        self._ai_test_lbl = QLabel()
        self._ai_test_lbl.setObjectName("muted")
        self._ai_test_lbl.setWordWrap(True)
        self._ai_test_lbl.setMaximumWidth(FW - 88)
        ext_test_row.addWidget(self._ai_test_btn)
        ext_test_row.addWidget(self._ai_test_lbl, 1)
        ext_test_row.setStretch(1, 1)
        gfl.addRow("", ext_test_row)

        def _run_ext_test():
            ak = self._ai_key.text().strip()
            bu = self._ai_url.text().strip()
            mdl = self._ai_model.text().strip()
            _fbw = self.focusWidget()

            def _restore():
                if _fbw and _fbw is not self._ai_test_btn and _fbw.isEnabled():
                    QTimer.singleShot(0, lambda: _fbw.setFocus(
                        Qt.FocusReason.OtherFocusReason))

            for val, key_miss, key_miss_d in [
                (ak,  "ai_err_api_key_missing", "ai_err_api_key_missing_detail"),
                (bu,  "ai_err_baseurl_missing", "ai_err_baseurl_missing_detail"),
                (mdl, "ai_err_model_missing",   "ai_err_model_missing_detail"),
            ]:
                if not val:
                    short = msg(key_miss)
                    detail = msg(key_miss_d)
                    self._ai_test_lbl.setText(_("✗  {}").format(short))
                    self._ai_test_lbl.setStyleSheet(status_label_qss("error"))
                    QMessageBox.warning(self, _("Settings"), detail)
                    return

            self._ai_test_btn.setEnabled(False)
            self._ai_test_lbl.setStyleSheet("")
            self._ai_test_lbl.setText(_("Testing…"))
            _restore()

            def _on_to():
                self._ai_test_lbl.setText(_("✗  {}").format("Timeout"))
                self._ai_test_lbl.setStyleSheet(status_label_qss("error"))
                self._ai_test_btn.setEnabled(True)
            _timer = threading.Timer(
                10.0, lambda: QTimer.singleShot(0, _on_to))
            _timer.start()

            def _ok(_text):
                try:
                    _timer.cancel()
                except Exception:
                    pass
                self._ai_test_lbl.setText(_("✓  Connected"))
                self._ai_test_lbl.setStyleSheet(
                    status_label_qss("success", _acc))
                self._ai_test_btn.setEnabled(True)

            def _err(short, detail):
                try:
                    _timer.cancel()
                except Exception:
                    pass
                self._ai_test_lbl.setText(_("✗  {}").format(short))
                self._ai_test_lbl.setStyleSheet(status_label_qss("error"))
                self._ai_test_btn.setEnabled(True)
                if detail:
                    mb = QMessageBox(QMessageBox.Warning, _("Settings"),
                                     short, parent=self)
                    mb.setDetailedText(detail)
                    mb.exec()

            def _on_st(raw_msg: str):
                key, kw = parse_status(raw_msg)
                if key:
                    text = msg(key, **kw)
                else:
                    text = kw.get("raw", raw_msg)
                QTimer.singleShot(0, lambda: self._ai_test_lbl.setText(text))

            from services.ai_service import AIWorker as _AIW
            _AIW.test(ak, bu, mdl, _ok, _err, on_status=_on_st)

        self._ai_test_btn.clicked.connect(_run_ext_test)
        aiv.addWidget(grp_ext)

        # Local model controls.
        grp_local = QGroupBox(_("Local Model"))
        lfl = QVBoxLayout(grp_local)
        lfl.setSpacing(10)
        lfl.setContentsMargins(10, 10, 10, 10)

        toggle_row = QWidget()
        tr_lyt = QHBoxLayout(toggle_row)
        tr_lyt.setContentsMargins(0, 0, 0, 0)
        tr_lyt.setSpacing(8)

        self._local_enabled_sw = SwitchButton(
            checked=app_ref.services.get_setting(
                LOCAL_MODEL_ENABLED_SETTING_KEY, "0") == "1",
            color_on=_acc, color_off=_off,
        )
        lbl_enable = QLabel(
            _("Enable local model"))
        lf2 = QFont()
        lf2.setBold(True)
        lbl_enable.setFont(lf2)
        tr_lyt.addWidget(lbl_enable)
        tr_lyt.addStretch()
        tr_lyt.addWidget(self._local_enabled_sw)
        lfl.addWidget(toggle_row)

        lbl_effect = QLabel(msg(
            "local_model_hint",
            "When enabled, text processing uses the local model first "
            "— no data is sent to external services.",
        ))
        lbl_effect.setWordWrap(True)
        lbl_effect.setObjectName("muted")
        lfl.addWidget(lbl_effect)

        self._local_status_lbl = QLabel()
        self._local_status_lbl.setObjectName("muted")
        lfl.addWidget(self._local_status_lbl)
        self._local_verify_bar = QProgressBar()
        self._local_verify_bar.setRange(0, 100)
        self._local_verify_bar.setValue(0)
        self._local_verify_bar.setVisible(False)
        lfl.addWidget(self._local_verify_bar)

        verify_ctrl = QWidget()
        verify_ctrl_l = QHBoxLayout(verify_ctrl)
        verify_ctrl_l.setContentsMargins(0, 0, 0, 0)
        verify_ctrl_l.setSpacing(8)
        self._local_verify_cancel_btn = QPushButton(_("Cancel"))
        self._local_verify_cancel_btn.setObjectName("action_btn")
        self._local_verify_cancel_btn.setVisible(False)
        verify_ctrl_l.addWidget(self._local_verify_cancel_btn)
        verify_ctrl_l.addStretch()
        lfl.addWidget(verify_ctrl)

        self._local_verify_cancel_event: threading.Event | None = None
        self._local_verify_seq = 0
        self._local_pending_entry_id = ""
        self._local_verify_bridge = _LocalVerifyBridge(self)

        # Single entry point for download/import/manage actions.
        btn_row_w = QWidget()
        btn_row_l = QHBoxLayout(btn_row_w)
        btn_row_l.setContentsMargins(0, 0, 0, 0)
        btn_row_l.setSpacing(8)
        self._local_dl_btn = QPushButton(
            _("Download"))
        self._local_dl_btn.setObjectName("action_btn")
        self._local_dl_blocked = False
        btn_row_l.addWidget(self._local_dl_btn)
        btn_row_l.addStretch()
        lfl.addWidget(btn_row_w)
        aiv.addWidget(grp_local)

        # Local model status refresh and verification flow.
        def _verify_reason_text(reason: str) -> str:
            mapping = {
                "timeout": msg(
                    "local_model_verify_timeout",
                    "Local model verification timed out.",
                ),
                "cancelled": msg(
                    "local_model_verify_cancelled",
                    "Local model verification was cancelled.",
                ),
                "permission_denied": msg(
                    "local_model_verify_permission_denied",
                    "Permission denied while verifying local model file.",
                ),
                "hash_mismatch": msg(
                    "local_model_verify_failed",
                    "Local model verification failed. Please re-download or switch model.",
                ),
                "io_error": msg(
                    "local_model_verify_failed",
                    "Local model verification failed. Please re-download or switch model.",
                ),
                "manifest_error": msg(
                    "local_model_verify_failed",
                    "Local model verification failed. Please re-download or switch model.",
                ),
            }
            return mapping.get(reason, "")

        def _apply_local_status(
            ready: bool,
            present: bool,
            lbl_text: str,
            verify_reason: str = "",
            verification_known: bool = True,
        ) -> None:
            enabled = self._local_enabled_sw.isChecked()
            self._local_verify_bar.setVisible(False)
            self._local_verify_cancel_btn.setVisible(False)
            self._local_verify_cancel_btn.setEnabled(False)
            if verification_known and ready and present:
                ready_text = _("Ready")
                activity_text = _("Active") if enabled else _("Inactive")
                status = "✓  " + ready_text
                if lbl_text:
                    status = f"✓  {lbl_text}  —  {ready_text} · {activity_text}"
                else:
                    status = f"✓  {ready_text} · {activity_text}"
                self._local_status_lbl.setText(status)
                self._local_status_lbl.setStyleSheet(
                    f"color:{_acc};font-weight:600;")
                self._local_dl_btn.setText(
                    _("Select / Change"))
            else:
                reason_text = _verify_reason_text(verify_reason)
                if verification_known and reason_text and present:
                    self._local_status_lbl.setText(reason_text)
                elif present:
                    if lbl_text:
                        self._local_status_lbl.setText(lbl_text)
                    else:
                        self._local_status_lbl.setText(_("Downloaded"))
                else:
                    self._local_status_lbl.setText(
                        _("Not downloaded"))
                self._local_status_lbl.setStyleSheet("")
                self._local_dl_btn.setText(
                    _("Select / Change") if present else _("Download"))
            if not enabled:
                self._local_dl_blocked = True
                self._local_dl_btn.setEnabled(False)
                self._local_dl_btn.setToolTip(
                    msg(
                        "local_model_inactive",
                        "Local model is inactive",
                    )
                )
                if app_ref.dark:
                    self._local_dl_btn.setStyleSheet(
                        local_model_download_blocked_qss(True))
                else:
                    self._local_dl_btn.setStyleSheet(
                        local_model_download_blocked_qss(False))
            else:
                self._local_dl_blocked = False
                self._local_dl_btn.setEnabled(True)
                self._local_dl_btn.setToolTip("")
                self._local_dl_btn.setStyleSheet("")

        def _invalidate_local_verify_cache(entry_id: str = "") -> None:
            if entry_id:
                SettingsDialog._session_local_verify_cache.pop(entry_id, None)
            else:
                SettingsDialog._session_local_verify_cache.clear()

        def _local_status_snapshot() -> tuple[bool, str, str, bool]:
            try:
                from services.local_model_service import (
                    get_active_entry_id,
                    get_entry,
                    load_catalog,
                    load_manifest,
                    get_models_dir,
                    localize_field,
                    LocalModelService,
                )
                mdir = get_models_dir()
                entry_id = str(get_active_entry_id(mdir) or "")
                present = bool(LocalModelService.get().is_model_present())
                manifest = load_manifest(mdir)
                manifest_entry = get_entry(manifest, entry_id or "local")
                has_expected_sha = bool(
                    str(manifest_entry.get("sha256", "")).strip()
                )
                catalog = load_catalog(mdir)
                cat = next(
                    (c for c in catalog if c.get("id") == entry_id),
                    catalog[0] if catalog else {},
                )
                lbl_text = localize_field(cat, "label", app_ref.lang) or cat.get("label", "")
                ready_hint = present and has_expected_sha
                return present, entry_id, str(lbl_text), bool(ready_hint)
            except Exception:
                return False, "", "", False

        def _cancel_local_verify() -> None:
            if self._local_verify_cancel_event is not None:
                self._local_verify_cancel_event.set()
            self._local_verify_cancel_btn.setEnabled(False)

        def _on_local_verify_progress(seq: int, percent: int) -> None:
            if seq != self._local_verify_seq:
                return
            self._local_verify_bar.setValue(max(0, min(100, int(percent))))

        def _on_local_verify_done(
            seq: int,
            ready: bool,
            present: bool,
            lbl_text: str,
            verify_reason: str,
        ) -> None:
            if seq != self._local_verify_seq:
                return
            entry_id = self._local_pending_entry_id
            if entry_id:
                SettingsDialog._session_local_verify_cache[entry_id] = (
                    bool(ready),
                    str(verify_reason),
                )
            SettingsDialog._session_local_verify_done = True
            _apply_local_status(ready, present, lbl_text, verify_reason)

        self._local_verify_bridge.progress.connect(_on_local_verify_progress)
        self._local_verify_bridge.done.connect(_on_local_verify_done)

        def _refresh_local_status(
            force_verify: bool = False,
            allow_initial_verify: bool = True,
            ignore_cache: bool = False,
        ) -> None:
            present, entry_id, lbl_text, ready_hint = _local_status_snapshot()
            self._local_pending_entry_id = entry_id
            enabled = self._local_enabled_sw.isChecked()
            should_verify = enabled and (
                force_verify
                or (allow_initial_verify and not SettingsDialog._session_local_verify_done)
            )
            cached = None if ignore_cache else SettingsDialog._session_local_verify_cache.get(entry_id, None)
            if not should_verify:
                if not present:
                    _invalidate_local_verify_cache(entry_id)
                if cached is not None:
                    ready_cached, reason_cached = cached
                    _apply_local_status(
                        bool(ready_cached) and present,
                        present,
                        lbl_text,
                        reason_cached,
                        verification_known=True,
                    )
                else:
                    _apply_local_status(
                        bool(ready_hint),
                        present,
                        lbl_text,
                        "",
                        verification_known=bool(ready_hint),
                    )
                return

            self._local_verify_seq += 1
            verify_seq = self._local_verify_seq
            if self._local_verify_cancel_event is not None:
                self._local_verify_cancel_event.set()
            cancel_event = threading.Event()
            self._local_verify_cancel_event = cancel_event
            self._local_verify_bar.setValue(0)
            self._local_verify_bar.setVisible(True)
            self._local_verify_cancel_btn.setVisible(True)
            self._local_verify_cancel_btn.setEnabled(True)

            self._local_status_lbl.setText(
                msg(
                    "local_model_verifying",
                    "Verifying local model file...",
                )
            )
            self._local_status_lbl.setStyleSheet("")
            self._local_dl_btn.setEnabled(False)

            def _worker() -> None:
                try:
                    from services.local_model_service import (
                        verify_model_file_with_reason,
                        get_models_dir,
                        LocalModelService,
                    )

                    def _progress(percent: int) -> None:
                        self._local_verify_bridge.progress.emit(verify_seq, int(percent))

                    mdir = get_models_dir()
                    active_id = entry_id
                    ready, verify_reason = verify_model_file_with_reason(
                        mdir,
                        active_id,
                        timeout_s=5.0,
                        retries=1,
                        progress_cb=_progress,
                        cancel_event=cancel_event,
                    )
                    present = LocalModelService.get().is_model_present()
                except Exception:
                    ready = False
                    present = bool(present)
                    verify_reason = "io_error"

                self._local_verify_bridge.done.emit(
                    verify_seq,
                    bool(ready),
                    bool(present),
                    str(lbl_text),
                    str(verify_reason),
                )

            threading.Thread(target=_worker, daemon=True).start()

        self._local_status_loaded = False

        def _ensure_local_status_loaded() -> None:
            if self._local_status_loaded:
                return
            self._local_status_loaded = True
            _refresh_local_status()

        def _on_local_toggle(checked: bool):
            app_ref.services.set_setting(
                LOCAL_MODEL_ENABLED_SETTING_KEY, "1" if checked else "0")
            if not checked:
                try:
                    from services.local_model_service import LocalModelService
                    LocalModelService.get().unload_provider()
                    LocalModelService.reset()
                except Exception:
                    pass
                _invalidate_local_verify_cache()
            _refresh_local_status(force_verify=False, allow_initial_verify=False)

        self._local_enabled_sw.toggled.connect(_on_local_toggle)
        self._local_verify_cancel_btn.clicked.connect(_cancel_local_verify)

        def _open_model_management() -> None:
            """Open the unified Model Management dialog."""
            if self._local_dl_blocked or not self._local_dl_btn.isEnabled():
                return
            from ui.dialogs.local_model_dialogs import LocalDownloadDialog
            themes_raw: Any = getattr(app_ref, "themes", None)
            themes_map: ThemeMap = themes_raw if isinstance(themes_raw, dict) else THEMES

            theme_raw: Any = getattr(app_ref, "theme", "blue")
            theme_name = theme_raw if isinstance(theme_raw, str) else "blue"
            theme_colors_raw = themes_map.get(theme_name) or themes_map.get("blue")
            theme_colors: ThemePalette = (
                theme_colors_raw if isinstance(theme_colors_raw, dict) else THEMES["blue"]
            )

            dark_mode = bool(getattr(app_ref, "dark", False))
            fallback_colors = THEMES["blue"][False]
            accent = theme_colors.get(
                dark_mode,
                theme_colors.get(False, fallback_colors),
            )[0]

            def _on_model_changed(event_name: str, entry_id: str) -> None:
                del event_name
                _invalidate_local_verify_cache(entry_id)
                QTimer.singleShot(
                    0,
                    lambda: _refresh_local_status(
                        force_verify=False,
                        allow_initial_verify=False,
                        ignore_cache=True,
                    ),
                )

            dlg = LocalDownloadDialog(
                self, app_ref.lang,
                accent_color=accent,
                dark=app_ref.dark,
                on_model_changed=_on_model_changed,
            )
            from services.local_model_service import (
                get_active_entry_id,
                get_models_dir,
                LocalModelService,
            )
            before_id = str(get_active_entry_id(get_models_dir()) or "")
            result = dlg.exec()
            after_id = str(get_active_entry_id(get_models_dir()) or "")
            LocalModelService.reset()
            from services.download_controller import DownloadController
            DownloadController.reset()
            changed = result == QDialog.Accepted and before_id != after_id
            if changed:
                _invalidate_local_verify_cache(after_id)
            _refresh_local_status(force_verify=changed, ignore_cache=True)

        self._local_dl_btn.clicked.connect(_open_model_management)

        aiv.addStretch()
        ai_tab_index = tabs.addTab(ai_scroll, _("AI"))
        tabs.currentChanged.connect(
            lambda idx: _ensure_local_status_loaded() if idx == ai_tab_index else None
        )
        QTimer.singleShot(0, lambda: _ensure_local_status_loaded() if tabs.currentIndex() == ai_tab_index else None)

        data_w = QWidget()
        dv = QVBoxLayout(data_w)
        dv.setContentsMargins(14, 14, 14, 14)
        dv.setSpacing(8)

        self._export_csv_btn = QPushButton(_("Export CSV"))
        self._import_csv_btn = QPushButton(_("Import CSV"))

        cal_grp = QGroupBox(_("Calendar Sync"))
        cv = QVBoxLayout(cal_grp)
        cv.setSpacing(6)
        cv.setContentsMargins(10, 10, 10, 10)
        cal_hint = QLabel(_("Import your .ics file to let AI read your meetings when generating reports."))
        cal_hint.setWordWrap(True)
        cal_hint.setObjectName("muted")
        cv.addWidget(cal_hint)
        self._ics_import_btn = QPushButton(_("📅 Import Calendar (.ics)"))
        self._ics_export_btn = QPushButton(_("Export .ics"))
        self._ics_clear_btn = QPushButton(_("Clear Calendar Events"))
        cv.addWidget(self._ics_import_btn)
        cv.addWidget(self._ics_export_btn)
        cv.addWidget(self._ics_clear_btn)

        for b in (self._export_csv_btn, self._import_csv_btn):
            dv.addWidget(b)
        dv.addWidget(cal_grp)
        dv.addStretch()
        tabs.addTab(data_w, _("Data"))

        about_w = QWidget()
        abv = QVBoxLayout(about_w)
        abv.setContentsMargins(24, 24, 24, 24)
        abv.setSpacing(10)
        abv.setAlignment(Qt.AlignTop)

        name_lbl = QLabel(_("Work Logger"))
        nf = QFont()
        nf.setPointSize(16)
        nf.setBold(True)
        name_lbl.setFont(nf)
        name_lbl.setAlignment(Qt.AlignCenter)
        abv.addWidget(name_lbl)

        ver_lbl = QLabel(f"{_("Version")}  {APP_VERSION}")
        ver_lbl.setAlignment(Qt.AlignCenter)
        ver_lbl.setObjectName("muted")
        abv.addWidget(ver_lbl)

        abv.addWidget(_div())

        desc_lbl = QLabel(_("A privacy-first desktop work-hours tracker with AI-powered reporting."))
        desc_lbl.setWordWrap(True)
        desc_lbl.setAlignment(Qt.AlignCenter)
        abv.addWidget(desc_lbl)

        abv.addSpacing(8)

        info_form = QFormLayout()
        info_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_form.setSpacing(6)
        info_form.addRow(_("Author"),  QLabel(APP_AUTHOR))
        lic_lbl = QLabel(f'<a href="{GPL_URL}">GNU GPL v3</a>')
        lic_lbl.setOpenExternalLinks(True)
        info_form.addRow(_("License"), lic_lbl)
        gh_lbl = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        gh_lbl.setOpenExternalLinks(True)
        info_form.addRow(_("GitHub"), gh_lbl)
        abv.addLayout(info_form)

        abv.addSpacing(12)

        self._features_btn = QPushButton(_("Features"))
        self._features_btn.setFixedWidth(200)
        self._features_btn.clicked.connect(self._show_feature_intro)
        abv.addWidget(self._features_btn, alignment=Qt.AlignCenter)

        self._check_upd_btn = QPushButton(_("Check for Updates"))
        self._check_upd_btn.setFixedWidth(200)
        self._check_upd_btn.clicked.connect(self._check_update)
        abv.addWidget(self._check_upd_btn, alignment=Qt.AlignCenter)

        self._upd_lbl = QLabel("")
        self._upd_lbl.setAlignment(Qt.AlignCenter)
        self._upd_lbl.setObjectName("muted")
        self._upd_lbl.setWordWrap(True)
        abv.addWidget(self._upd_lbl)

        abv.addStretch()
        tabs.addTab(about_w, _("About"))

        lv.addWidget(tabs)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText(_("OK"))
        btns.button(QDialogButtonBox.Cancel).setText(
            _("Cancel"))
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        lv.addWidget(btns)

    def _sync_custom_theme_controls(self, *_args) -> None:
        is_custom = self._theme_cb.currentData() == "custom"
        self._custom_color_btn.setVisible(is_custom)
        self._custom_color_btn.setEnabled(is_custom)
        self._custom_color_btn.setStyleSheet(
            "QPushButton{"
            f"background:{self._custom_color};"
            "border:1px solid #80889a;"
            "border-radius:8px;"
            "}"
            "QPushButton:hover{border:1px solid #ffffff;}"
        )

    def _apply_custom_color(self, hex_color: str) -> None:
        app = self._app
        state = app.services.set_custom_theme(hex_color)
        self._custom_color = state.custom_color or DEFAULT_CUSTOM_COLOR
        set_custom_theme(self._custom_color)
        app.themes["custom"] = dict(THEMES["custom"])
        self._theme_cb.blockSignals(True)
        try:
            idx = self._theme_cb.findData("custom")
            if idx >= 0:
                self._theme_cb.setCurrentIndex(idx)
        finally:
            self._theme_cb.blockSignals(False)
        app.store.patch(theme="custom", custom_color=self._custom_color)
        app.apply_theme()
        app.render()
        self._sync_custom_theme_controls()

    def _open_custom_color_dialog(self) -> None:
        from .color_picker_dialog import ColorPickerDialog

        dlg = ColorPickerDialog(self._custom_color, self)
        dlg.color_selected.connect(self._apply_custom_color)
        dlg.exec()

    def _on_minimal_mode_toggled(self, enabled: bool) -> None:
        app = self._app
        app.store.patch(minimal_mode=enabled)
        app.services.set_setting(MINIMAL_MODE_SETTING_KEY, "1" if enabled else "0")
        QMessageBox.information(
            self,
            msg("restart_required"),
            msg("minimal_mode_toggle_restart"),
        )
        self.accept()

    def _show_feature_intro(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(_("Feature Overview"))
        dlg.setMinimumSize(520, 420)
        dlg.resize(620, 500)

        lv = QVBoxLayout(dlg)
        lv.setContentsMargins(16, 16, 16, 16)
        lv.setSpacing(10)

        intro = QTextEdit()
        intro.setReadOnly(True)
        intro.setPlainText(
            _(
                """Work Logger is a flexible desktop app for tracking work hours, notes, and reports.

What you can do:
- Switch between Manual Input and Auto Record depending on how you like to log time.
- Record start time, end time, and break time for each day.
- Save work type and notes together with the time record.
- Use Quick Log for lightweight task entries during the day.
- Keep notes for future dates even when exact work hours are not decided yet.
- Generate daily, weekly, and monthly reports from saved data.
- Use AI-compatible providers to turn notes into polished summaries.
- Review monthly trends with charts, averages, overtime, and monthly targets.
- Import calendar events and display public holidays.
- Customize language, theme, AI settings, and reminder behavior.

Recommended workflow:
1. Pick Manual Input if you usually type times yourself.
2. Pick Auto Record if you prefer start/end/break buttons.
3. Add Notes or Quick Log entries as work happens.
4. Save the day record when finished.
5. Open Reports or AI tools when you need a summary.

Helpful details:
- Holiday names can be shown automatically on the calendar.
- A small reminder dot can appear on days that only have notes.
- Built-in and custom templates can be used in notes and reports."""
            )
        )
        lv.addWidget(intro, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.button(QDialogButtonBox.Ok).setText(_("OK"))
        btns.accepted.connect(dlg.accept)
        lv.addWidget(btns)

        dlg.exec()

    def _check_update(self):
        self._check_upd_btn.setEnabled(False)
        self._upd_lbl.setText(_("Checking for updates…"))
        tr = get_translator(self._app.lang).gettext
        self._app.services.check_update_async(tr, self._upd_done)

    def _upd_done(self, msg: str):
        self._upd_lbl.setText(msg)
        self._check_upd_btn.setEnabled(True)

    def _apply(self):
        app = self._app
        app.work_hours = self._wh.value()
        app.services.set_setting(WORK_HOURS_SETTING_KEY, str(app.work_hours))
        app.services.set_setting(DEFAULT_BREAK_SETTING_KEY, str(self._dl.value()))
        app.services.set_setting(MONTHLY_TARGET_SETTING_KEY, str(self._mt.value()))
        app.services.set_secret("ai_api_key", self._ai_key.text().strip())
        app.services.set_setting("ai_base_url", self._ai_url.text().strip())
        app.services.set_setting("ai_model", self._ai_model.text().strip())
        app.services.set_setting(
            LOCAL_MODEL_ENABLED_SETTING_KEY,
            "1" if self._local_enabled_sw.isChecked() else "0"
        )

        new_show_hol = self._show_holidays.isChecked()
        old_show_hol = app.services.get_setting(SHOW_HOLIDAYS_SETTING_KEY, "1") == "1"
        app.services.set_setting(SHOW_HOLIDAYS_SETTING_KEY, "1" if new_show_hol else "0")
        holidays_changed = new_show_hol != old_show_hol
        new_show_note_markers = self._show_note_markers.isChecked()
        old_show_note_markers = app.services.get_setting(
            SHOW_NOTE_MARKERS_SETTING_KEY, "1") == "1"
        app.services.set_setting(SHOW_NOTE_MARKERS_SETTING_KEY,
                                 "1" if new_show_note_markers else "0")
        note_markers_changed = new_show_note_markers != old_show_note_markers
        new_show_overnight_indicator = self._show_overnight_indicator.isChecked()
        old_show_overnight_indicator = app.services.get_setting(
            SHOW_OVERNIGHT_INDICATOR_SETTING_KEY, "1") == "1"
        app.services.set_setting(
            SHOW_OVERNIGHT_INDICATOR_SETTING_KEY,
            "1" if new_show_overnight_indicator else "0",
        )
        overnight_indicator_changed = (
            new_show_overnight_indicator != old_show_overnight_indicator
        )
        new_week_start = self._week_start_monday.isChecked(
        ) if hasattr(self, '_week_start_monday') else False
        old_week_start = app.services.get_setting(
            WEEK_START_MONDAY_SETTING_KEY, "0") == "1"
        app.services.set_setting(
            WEEK_START_MONDAY_SETTING_KEY, "1" if new_week_start else "0")
        week_start_changed = new_week_start != old_week_start
        new_minimal_mode = app.store.state.minimal_mode
        residency_changed = False
        if self._residency_key and self._residency_switch is not None:
            new_residency = self._residency_switch.isChecked()
            old_residency = app.services.get_setting(
                self._residency_key, "0") == "1"
            app.services.set_setting(self._residency_key,
                                     "1" if new_residency else "0")
            residency_changed = new_residency != old_residency

        new_lang = self._lang_cb.currentData()
        new_dark = self._dark.isChecked()
        new_theme = self._theme_cb.currentData()
        lang_changed = new_lang != app.lang
        dark_changed = new_dark != app.dark
        theme_changed = new_theme != app.theme
        app.lang = new_lang
        app.dark = new_dark
        app.theme = new_theme
        app.services.set_setting(LANG_SETTING_KEY, new_lang)
        app.services.set_setting(DARK_MODE_SETTING_KEY, "1" if new_dark else "0")
        if new_theme == "custom":
            state = app.services.set_custom_theme(self._custom_color)
            self._custom_color = state.custom_color or DEFAULT_CUSTOM_COLOR
            set_custom_theme(self._custom_color)
            app.themes["custom"] = dict(THEMES["custom"])
        else:
            app.services.set_setting(THEME_SETTING_KEY, new_theme)
        app.store.patch(
            lang=new_lang,
            theme=new_theme,
            custom_color=self._custom_color,
            dark=new_dark,
            work_hours=app.work_hours,
            default_break=float(self._dl.value()),
            monthly_target=float(self._mt.value()),
            show_holidays=new_show_hol,
            show_note_markers=new_show_note_markers,
            show_overnight_indicator=new_show_overnight_indicator,
            week_start_monday=new_week_start,
            time_input_mode=app._active_time_tab,
            minimal_mode=new_minimal_mode,
        )
        if dark_changed or theme_changed:
            app.apply_theme()
        if lang_changed:
            app.apply_lang()
        if residency_changed or lang_changed:
            app._update_residency_state()
        if holidays_changed and not app.store.state.minimal_mode:
            if new_show_hol:
                app._load_holidays()
            else:
                app.holidays = {}
        if note_markers_changed:
            app.render()
        if overnight_indicator_changed:
            app.render()
        if week_start_changed:
            app.render()
        app.render()
        self.accept()
