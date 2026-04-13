from __future__ import annotations
import sys

from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QPushButton, QLabel, QLineEdit, QTextEdit, QScrollArea, QMessageBox,
    QDoubleSpinBox, QGroupBox, QDialogButtonBox, QComboBox,
    QFrame, QFileDialog,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from config.i18n import T, LANG_KEYS, LANG_NAMES
from config.constants import APP_VERSION, APP_AUTHOR, GITHUB_URL, GPL_URL
from config.themes import THEMES, THEME_KEYS, THEME_NAMES
from utils.ai_status_formatter import render_status_text
from ui.widgets import SwitchButton
from .common import _div, _localize_msgbox_buttons


class SettingsDialog(QDialog):
    def __init__(self, app_ref, parent=None):
        super().__init__(parent)
        self._app = app_ref
        t = T[app_ref.lang]
        self.setWindowTitle(t["settings_title"])
        self.setMinimumSize(450, 500)
        self.resize(450, 590)
        self.setModal(True)

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
        for k in LANG_KEYS:
            self._lang_cb.addItem(LANG_NAMES[k], k)
        idx = self._lang_cb.findData(app_ref.lang)
        if idx >= 0:
            self._lang_cb.setCurrentIndex(idx)
        af.addRow(t["lbl_language"].lstrip("🌍 "), self._lang_cb)

        _acc = THEMES[app_ref.theme][app_ref.dark][0]
        _off_col = "#505470" if app_ref.dark else "#b0b8cc"
        dark_wrap = QWidget()
        dh = QHBoxLayout(dark_wrap)
        dh.setContentsMargins(0, 0, 0, 0)
        self._dark = SwitchButton(checked=app_ref.dark,
                                  color_on=_acc, color_off=_off_col)
        dh.addWidget(self._dark)
        dh.addStretch()
        af.addRow(t["lbl_darkmode"].lstrip("🌙☀ "), dark_wrap)

        self._theme_cb = QComboBox()
        self._theme_cb.setFixedWidth(FW)
        for k in THEME_KEYS:
            self._theme_cb.addItem(THEME_NAMES[k], k)
        idx2 = self._theme_cb.findData(app_ref.theme)
        if idx2 >= 0:
            self._theme_cb.setCurrentIndex(idx2)
        af.addRow(t["theme_label"].lstrip("🎨 "), self._theme_cb)
        tabs.addTab(app_w, t["tab_appearance"])

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
        gf.addRow(t["std_hours"], self._wh)

        self._dl = QDoubleSpinBox()
        self._dl.setFixedWidth(FW)
        self._dl.setRange(0.0, 4.0)
        self._dl.setSingleStep(0.5)
        self._dl.setValue(app_ref._safe_float_setting("default_break", 1.0))
        gf.addRow(t["default_break"], self._dl)

        self._mt = QDoubleSpinBox()
        self._mt.setFixedWidth(FW)
        self._mt.setRange(0.0, 400.0)
        self._mt.setSingleStep(8.0)
        self._mt.setValue(app_ref._safe_float_setting(
            "monthly_target", round(app_ref.work_hours * 21, 1)))
        gf.addRow(t["monthly_target"], self._mt)

        _show_hol_on = app_ref.services.get_setting("show_holidays", "1") == "1"
        show_hol_wrap = QWidget()
        sh = QHBoxLayout(show_hol_wrap)
        sh.setContentsMargins(0, 0, 0, 0)
        self._show_holidays = SwitchButton(checked=_show_hol_on,
                                           color_on=_acc, color_off=_off_col)
        sh.addWidget(self._show_holidays)
        sh.addStretch()
        gf.addRow(t["lbl_show_holidays"], show_hol_wrap)

        _show_note_markers_on = app_ref.services.get_setting(
            "show_note_markers", "1") == "1"
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
        gf.addRow(t["lbl_show_note_markers"], show_note_markers_wrap)

        _week_start_on = app_ref.services.get_setting("week_start_monday", "0") == "1"
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
        gf.addRow(t.get("lbl_week_start_monday", "Start week on Monday"), week_start_wrap)

        residency_key = "enable_tray" if sys.platform == "win32" else (
            "enable_menu_bar" if sys.platform == "darwin" else ""
        )
        if residency_key:
            residency_wrap = QWidget()
            rs = QHBoxLayout(residency_wrap)
            rs.setContentsMargins(0, 0, 0, 0)
            self._residency_switch = SwitchButton(
                checked=app_ref.services.get_setting(residency_key, "0") == "1",
                color_on=_acc,
                color_off=_off_col,
            )
            rs.addWidget(self._residency_switch)
            rs.addStretch()
            residency_label = "lbl_enable_tray" if sys.platform == "win32" else "lbl_enable_menu_bar"
            gf.addRow(t[residency_label], residency_wrap)
        else:
            self._residency_switch = None
            residency_key = ""
        self._residency_key = residency_key

        tabs.addTab(gen_w, t["tab_general"])

        ai_scroll = QScrollArea()
        ai_scroll.setWidgetResizable(True)
        ai_inner = QWidget()
        ai_scroll.setWidget(ai_inner)
        aiv = QVBoxLayout(ai_inner)
        aiv.setContentsMargins(14, 14, 14, 14)
        aiv.setSpacing(12)

        _acc = THEMES[app_ref.theme][app_ref.dark][0]
        _off = "#505470" if app_ref.dark else "#b0b8cc"

        # ── External Model group (ex-Primary AI) ──────────────────────────
        grp_ext = QGroupBox(t.get("ai_external_group", "External Model"))
        gfl = QFormLayout(grp_ext)
        gfl.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        gfl.setSpacing(8)
        gfl.setContentsMargins(10, 10, 10, 10)

        def _ai_line(placeholder=""):
            le = QLineEdit()
            le.setFixedWidth(FW)
            le.setPlaceholderText(placeholder)
            return le

        self._ai_key = _ai_line(t.get("ai_key_placeholder", "sk-… / sk-ant-…"))
        self._ai_key.setEchoMode(QLineEdit.Password)
        self._ai_key.setText(app_ref.services.get_setting("ai_api_key", ""))
        gfl.addRow(t["ai_api_key"], self._ai_key)

        self._ai_url = _ai_line(
            t.get("ai_url_placeholder",
                  "https://api.openai.com/v1 | https://api.anthropic.com"))
        self._ai_url.setText(app_ref.services.get_setting("ai_base_url", ""))
        gfl.addRow(t["ai_base_url"], self._ai_url)

        self._ai_model = _ai_line(
            t.get("ai_model_placeholder", "gpt-4o-mini | claude-haiku-4-5-20251001"))
        self._ai_model.setText(app_ref.services.get_setting("ai_model", ""))
        gfl.addRow(t["ai_model"], self._ai_model)

        ext_test_row = QHBoxLayout()
        ext_test_row.setSpacing(8)
        self._ai_test_btn = QPushButton(t["ai_test_btn"])
        self._ai_test_btn.setObjectName("action_btn")
        self._ai_test_btn.setFixedWidth(80)
        self._ai_test_lbl = QLabel()
        self._ai_test_lbl.setObjectName("muted")
        ext_test_row.addWidget(self._ai_test_btn)
        ext_test_row.addWidget(self._ai_test_lbl, 1)
        gfl.addRow("", ext_test_row)

        def _run_ext_test():
            ak  = self._ai_key.text().strip()
            bu  = self._ai_url.text().strip()
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
                    short  = t.get(key_miss, key_miss)
                    detail = t.get(key_miss_d, key_miss_d)
                    self._ai_test_lbl.setText(t["ai_test_fail"].format(short))
                    self._ai_test_lbl.setStyleSheet("color:#e03333;font-weight:600;")
                    QMessageBox.warning(self, t["settings_title"], detail)
                    return

            self._ai_test_btn.setEnabled(False)
            self._ai_test_lbl.setStyleSheet("")
            self._ai_test_lbl.setText(t["ai_test_testing"])
            _restore()

            def _on_to():
                self._ai_test_lbl.setText(t["ai_test_fail"].format("Timeout"))
                self._ai_test_lbl.setStyleSheet("color:#e03333;font-weight:600;")
                self._ai_test_btn.setEnabled(True)
            _timer = threading.Timer(10.0, lambda: QTimer.singleShot(0, _on_to))
            _timer.start()

            def _ok(_text):
                try: _timer.cancel()
                except Exception: pass
                self._ai_test_lbl.setText(t["ai_test_ok"])
                self._ai_test_lbl.setStyleSheet(f"color:{_acc};font-weight:600;")
                self._ai_test_btn.setEnabled(True)

            def _err(short, detail):
                try: _timer.cancel()
                except Exception: pass
                self._ai_test_lbl.setText(t["ai_test_fail"].format(short))
                self._ai_test_lbl.setStyleSheet("color:#e03333;font-weight:600;")
                self._ai_test_btn.setEnabled(True)
                if detail:
                    mb = QMessageBox(QMessageBox.Warning, t["settings_title"],
                                     short, parent=self)
                    mb.setDetailedText(detail)
                    mb.exec()

            def _on_st(msg):
                text = render_status_text(msg, T[app_ref.lang])
                QTimer.singleShot(0, lambda: self._ai_test_lbl.setText(text))

            from services.ai_service import AIWorker as _AIW
            _AIW.test(ak, bu, mdl, _ok, _err, on_status=_on_st)

        self._ai_test_btn.clicked.connect(_run_ext_test)
        aiv.addWidget(grp_ext)

        # ── Local Model group ─────────────────────────────────────────────
        grp_local = QGroupBox(t.get("ai_local_group", "Local Model"))
        lfl = QVBoxLayout(grp_local)
        lfl.setSpacing(10)
        lfl.setContentsMargins(10, 10, 10, 10)

        # Toggle row: [label]  [switch]
        toggle_row = QWidget()
        tr_lyt = QHBoxLayout(toggle_row)
        tr_lyt.setContentsMargins(0, 0, 0, 0)
        tr_lyt.setSpacing(8)

        self._local_enabled_sw = SwitchButton(
            checked=app_ref.services.get_setting("local_model_enabled", "0") == "1",
            color_on=_acc, color_off=_off,
        )
        lbl_enable = QLabel(t.get("local_model_enable_label", "Enable local model"))
        lf2 = QFont()
        lf2.setBold(True)
        lbl_enable.setFont(lf2)
        tr_lyt.addWidget(lbl_enable)
        tr_lyt.addStretch()
        tr_lyt.addWidget(self._local_enabled_sw)
        lfl.addWidget(toggle_row)

        # Secondary description line
        lbl_effect = QLabel(t.get(
            "local_model_hint",
            "When enabled, text processing uses the local model first "
            "— no data is sent to external services.",
        ))
        lbl_effect.setWordWrap(True)
        lbl_effect.setObjectName("muted")
        lfl.addWidget(lbl_effect)

        # Status label
        self._local_status_lbl = QLabel()
        self._local_status_lbl.setObjectName("muted")
        lfl.addWidget(self._local_status_lbl)

        # Single "Model Management" button (opens unified dialog)
        btn_row_w = QWidget()
        btn_row_l = QHBoxLayout(btn_row_w)
        btn_row_l.setContentsMargins(0, 0, 0, 0)
        btn_row_l.setSpacing(8)
        self._local_dl_btn = QPushButton(t.get("local_model_download_btn", "Download"))
        self._local_dl_btn.setObjectName("action_btn")
        btn_row_l.addWidget(self._local_dl_btn)
        btn_row_l.addStretch()
        lfl.addWidget(btn_row_w)
        aiv.addWidget(grp_local)

        # ── Local model status refresh ────────────────────────────────────
        def _refresh_local_status() -> None:
            try:
                from services.local_model_service import (
                    verify_model_file, get_active_entry_id,
                    load_catalog, get_models_dir, localize_field,
                )
                mdir     = get_models_dir()
                entry_id = get_active_entry_id(mdir)
                ready    = verify_model_file(mdir, entry_id)
                catalog  = load_catalog(mdir)
                cat      = next((c for c in catalog
                                 if c.get("id") == entry_id),
                                catalog[0] if catalog else {})
                # Use inline label from catalog (no i18n key indirection)
                lbl_text = localize_field(cat, "label", app_ref.lang) or cat.get("label", "")
            except Exception:
                ready    = False
                lbl_text = ""
            if ready:
                status = "✓  " + t.get("local_model_status_ready", "Ready")
                if lbl_text:
                    status = f"✓  {lbl_text}  —  {t.get('local_model_status_ready', 'Ready')}"
                self._local_status_lbl.setText(status)
                self._local_status_lbl.setStyleSheet(
                    f"color:{_acc};font-weight:600;")
                self._local_dl_btn.setText(
                    t.get("local_model_select_btn", "Select / Change"))
            else:
                self._local_status_lbl.setText(
                    t.get("local_model_status_not_downloaded", "Not downloaded"))
                self._local_status_lbl.setStyleSheet("")
                self._local_dl_btn.setText(
                    t.get("local_model_download_btn", "Download"))

        _refresh_local_status()

        def _open_model_management():
            """Open the unified Model Management dialog."""
            from ui.dialogs.local_model_dialogs import LocalDownloadDialog
            from config.themes import THEMES
            theme_colors = THEMES.get(app_ref.theme, THEMES["blue"])
            accent = theme_colors.get(app_ref.dark, theme_colors.get(False, ("",)))[0]
            dlg = LocalDownloadDialog(
                self, app_ref.lang,
                accent_color=accent,
                dark=app_ref.dark,
            )
            dlg.exec()
            from services.local_model_service import LocalModelService
            LocalModelService.reset()
            from services.download_controller import DownloadController
            DownloadController.reset()
            _refresh_local_status()

        self._local_dl_btn.clicked.connect(_open_model_management)

        aiv.addStretch()
        tabs.addTab(ai_scroll, t["tab_ai"])

        data_w = QWidget()
        dv = QVBoxLayout(data_w)
        dv.setContentsMargins(14, 14, 14, 14)
        dv.setSpacing(8)

        self._export_csv_btn = QPushButton(t["export_csv"])
        self._import_csv_btn = QPushButton(t["import_csv"])

        cal_grp = QGroupBox(t["cal_section"])
        cv = QVBoxLayout(cal_grp)
        cv.setSpacing(6)
        cv.setContentsMargins(10, 10, 10, 10)
        cal_hint = QLabel(t["cal_hint"])
        cal_hint.setWordWrap(True)
        cal_hint.setObjectName("muted")
        cv.addWidget(cal_hint)
        self._ics_import_btn = QPushButton(t["cal_import_btn"])
        self._ics_export_btn = QPushButton(t["ics_export"])
        self._ics_clear_btn = QPushButton(t["cal_clear"])
        cv.addWidget(self._ics_import_btn)
        cv.addWidget(self._ics_export_btn)
        cv.addWidget(self._ics_clear_btn)

        for b in (self._export_csv_btn, self._import_csv_btn):
            dv.addWidget(b)
        dv.addWidget(cal_grp)
        dv.addStretch()
        tabs.addTab(data_w, t["tab_data"])

        about_w = QWidget()
        abv = QVBoxLayout(about_w)
        abv.setContentsMargins(24, 24, 24, 24)
        abv.setSpacing(10)
        abv.setAlignment(Qt.AlignTop)

        name_lbl = QLabel(t["about_app_name"])
        nf = QFont()
        nf.setPointSize(16)
        nf.setBold(True)
        name_lbl.setFont(nf)
        name_lbl.setAlignment(Qt.AlignCenter)
        abv.addWidget(name_lbl)

        ver_lbl = QLabel(f"{t['about_version']}  {APP_VERSION}")
        ver_lbl.setAlignment(Qt.AlignCenter)
        ver_lbl.setObjectName("muted")
        abv.addWidget(ver_lbl)

        abv.addWidget(_div())

        desc_lbl = QLabel(t["about_desc"])
        desc_lbl.setWordWrap(True)
        desc_lbl.setAlignment(Qt.AlignCenter)
        abv.addWidget(desc_lbl)

        abv.addSpacing(8)

        info_form = QFormLayout()
        info_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        info_form.setSpacing(6)
        info_form.addRow(t["about_author"],  QLabel(APP_AUTHOR))
        lic_lbl = QLabel(f'<a href="{GPL_URL}">GNU GPL v3</a>')
        lic_lbl.setOpenExternalLinks(True)
        info_form.addRow(t["about_license"], lic_lbl)
        gh_lbl = QLabel(f'<a href="{GITHUB_URL}">{GITHUB_URL}</a>')
        gh_lbl.setOpenExternalLinks(True)
        info_form.addRow(t["about_github"], gh_lbl)
        abv.addLayout(info_form)

        abv.addSpacing(12)

        self._features_btn = QPushButton(t["about_features_btn"])
        self._features_btn.setFixedWidth(200)
        self._features_btn.clicked.connect(self._show_feature_intro)
        abv.addWidget(self._features_btn, alignment=Qt.AlignCenter)

        self._check_upd_btn = QPushButton(t["about_check_update"])
        self._check_upd_btn.setFixedWidth(200)
        self._check_upd_btn.clicked.connect(self._check_update)
        abv.addWidget(self._check_upd_btn, alignment=Qt.AlignCenter)

        self._upd_lbl = QLabel("")
        self._upd_lbl.setAlignment(Qt.AlignCenter)
        self._upd_lbl.setObjectName("muted")
        self._upd_lbl.setWordWrap(True)
        abv.addWidget(self._upd_lbl)

        abv.addStretch()
        tabs.addTab(about_w, t["tab_about"])

        lv.addWidget(tabs)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText(t.get("btn_ok", "OK"))
        btns.button(QDialogButtonBox.Cancel).setText(
            t.get("btn_cancel", "Cancel"))
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        lv.addWidget(btns)

    def _show_feature_intro(self):
        t = T[self._app.lang]
        dlg = QDialog(self)
        dlg.setWindowTitle(t["about_features_title"])
        dlg.setMinimumSize(520, 420)
        dlg.resize(620, 500)

        lv = QVBoxLayout(dlg)
        lv.setContentsMargins(16, 16, 16, 16)
        lv.setSpacing(10)

        intro = QTextEdit()
        intro.setReadOnly(True)
        intro.setPlainText(t["about_features_body"])
        lv.addWidget(intro, 1)

        btns = QDialogButtonBox(QDialogButtonBox.Ok)
        btns.button(QDialogButtonBox.Ok).setText(t.get("btn_ok", "OK"))
        btns.accepted.connect(dlg.accept)
        lv.addWidget(btns)

        dlg.exec()

    def _check_update(self):
        t = T[self._app.lang]
        self._check_upd_btn.setEnabled(False)
        self._upd_lbl.setText(t.get("about_update_checking", "Checking…"))
        self._app.services.check_update_async(t, self._upd_done)

    def _upd_done(self, msg: str):
        self._upd_lbl.setText(msg)
        self._check_upd_btn.setEnabled(True)

    def _apply(self):
        app = self._app
        app.work_hours = self._wh.value()
        app.services.set_setting("work_hours", str(app.work_hours))
        app.services.set_setting("default_break", str(self._dl.value()))
        app.services.set_setting("monthly_target", str(self._mt.value()))
        app.services.set_setting("ai_api_key", self._ai_key.text().strip())
        app.services.set_setting("ai_base_url", self._ai_url.text().strip())
        app.services.set_setting("ai_model", self._ai_model.text().strip())
        app.services.set_setting(
            "local_model_enabled",
            "1" if self._local_enabled_sw.isChecked() else "0"
        )

        new_show_hol = self._show_holidays.isChecked()
        old_show_hol = app.services.get_setting("show_holidays", "1") == "1"
        app.services.set_setting("show_holidays", "1" if new_show_hol else "0")
        holidays_changed = new_show_hol != old_show_hol
        new_show_note_markers = self._show_note_markers.isChecked()
        old_show_note_markers = app.services.get_setting(
            "show_note_markers", "1") == "1"
        app.services.set_setting("show_note_markers",
                                 "1" if new_show_note_markers else "0")
        note_markers_changed = new_show_note_markers != old_show_note_markers
        new_week_start = self._week_start_monday.isChecked() if hasattr(self, '_week_start_monday') else False
        old_week_start = app.services.get_setting("week_start_monday", "0") == "1"
        app.services.set_setting("week_start_monday", "1" if new_week_start else "0")
        week_start_changed = new_week_start != old_week_start
        residency_changed = False
        if self._residency_key and self._residency_switch is not None:
            new_residency = self._residency_switch.isChecked()
            old_residency = app.services.get_setting(self._residency_key, "0") == "1"
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
        app.services.set_setting("lang", new_lang)
        app.services.set_setting("dark", "1" if new_dark else "0")
        app.services.set_setting("theme", new_theme)
        app.store.patch(
            lang=new_lang,
            theme=new_theme,
            dark=new_dark,
            work_hours=app.work_hours,
            default_break=float(self._dl.value()),
            monthly_target=float(self._mt.value()),
            show_holidays=new_show_hol,
            show_note_markers=new_show_note_markers,
            week_start_monday=new_week_start,
            time_input_mode=app._active_time_tab,
        )
        if dark_changed or theme_changed:
            app.apply_theme()
        if lang_changed:
            app.apply_lang()
        if residency_changed or lang_changed:
            app._update_residency_state()
        if holidays_changed:
            if new_show_hol:
                app._load_holidays()
            else:
                app.holidays = {}
        if note_markers_changed:
            app.render()
        if week_start_changed:
            app.render()
        app.render()
        self.accept()
