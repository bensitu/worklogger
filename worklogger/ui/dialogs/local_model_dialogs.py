"""Local model management dialogs.

UI/logic separation
-------------------
All business logic lives in ``services/local_model_service.py`` and
``services/download_controller.py``.  This module only contains:

* ``_Bridge``             — Qt signal bridge (thread → main thread)
* ``LocalDownloadDialog`` — two-page UI (model selection + download progress)

The dialog never imports ``DownloadController`` directly in its __init__;
it wires callbacks to the controller only at the moment the user clicks
"Download", keeping Qt startup free of service imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTextEdit, QMessageBox, QFileDialog,
    QButtonGroup, QRadioButton, QGroupBox, QScrollArea, QWidget,
    QFrame, QStackedWidget,
)
from PySide6.QtGui import QFont

from utils.i18n import _, msg
from config.themes import progress_bar_qss


# ---------------------------------------------------------------------------
# Cross-thread bridge
# ---------------------------------------------------------------------------

class _Bridge(QObject):
    """Qt-signal bridge for DownloadController callbacks → main thread.

    Signals are emitted directly from the background thread; Qt's
    queued-connection delivers them to the main-thread event loop.
    No QTimer.singleShot wrappers are needed.
    """
    progress = Signal(
        object, object)  # int64-safe; avoids Qt 32-bit overflow for files >2 GB
    status = Signal(str)        # i18n key
    done = Signal()
    error = Signal(str)        # error message / i18n key


# ---------------------------------------------------------------------------
# LocalDownloadDialog — two-page flow
# ---------------------------------------------------------------------------

class LocalDownloadDialog(QDialog):
    """Two-page modal: model selection (Page 0) → download progress (Page 1).

    All service calls are deferred to the moment they are needed:
    - Catalog is read only when page 0 is built.
    - DownloadController is started only when the user confirms download.
    - LocalModelService is reset only after a successful download/import.

    This keeps the dialog constructor lightweight and import-side-effect free.
    """

    PAGE_SELECT = 0
    PAGE_DOWNLOAD = 1

    def __init__(self, parent, lang: str,
                 accent_color: str = "#4f8ef7",
                 dark: bool = False) -> None:
        super().__init__(parent)
        self._lang = lang
        self._accent_color = accent_color
        self._dark = dark
        self._bridge = _Bridge(self)
        self._sel_id: Optional[str] = None
        self.setWindowTitle(_("Download Local Model"))
        self.setMinimumSize(580, 480)
        self.resize(620, 520)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)
        self._stack.addWidget(self._build_select_page(t_dict))
        self._stack.addWidget(self._build_download_page(t_dict))

        self._bridge.progress.connect(self._on_progress)
        self._bridge.status.connect(self._on_status)
        self._bridge.done.connect(self._on_done)
        self._bridge.error.connect(self._on_error)

        self._show_page(self.PAGE_SELECT)

    # ── Page 0: model selection ─────────────────────────────────────────────

    def _build_select_page(self, t: dict) -> QWidget:
        from services.local_model_service import (
            ensure_catalog, load_catalog, get_active_entry_id,
            localize_field, get_models_dir,
        )
        # Ensure catalog.json exists in user models dir (critical on first frozen run)
        try:
            ensure_catalog(get_models_dir())
        except Exception:
            pass
        catalog   = load_catalog()
        active_id = get_active_entry_id()

        page = QWidget()
        lyt = QVBoxLayout(page)
        lyt.setContentsMargins(16, 16, 16, 16)
        lyt.setSpacing(10)

        title = QLabel(_("Choose a model to download"))
        tf = QFont()
        tf.setPointSize(11)
        tf.setBold(True)
        title.setFont(tf)
        lyt.addWidget(title)

        hint = QLabel(msg(
            "local_model_select_hint",
            "Only one model can be active at a time.  "
            "Delete the current model before switching.",
        ))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lyt.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        cards_w = QWidget()
        cards_l = QVBoxLayout(cards_w)
        cards_l.setSpacing(8)
        cards_l.setContentsMargins(0, 0, 0, 0)

        self._radio_group = QButtonGroup(page)
        self._radio_group.setExclusive(True)
        self._card_widgets: dict = {}

        lang = self._lang
        for entry in catalog:
            eid = entry.get("id", "")
            card = self._build_model_card(entry, t, lang)
            self._card_widgets[eid] = card
            self._radio_group.addButton(card["radio"])
            cards_l.addWidget(card["frame"])

        cards_l.addStretch()
        scroll.setWidget(cards_w)
        lyt.addWidget(scroll, 1)

        self._refresh_card_states()

        btn_row = QHBoxLayout()
        self._sel_cancel_btn = QPushButton(
            _("Cancel"))
        self._sel_import_btn = QPushButton(
            _("Import .gguf"))
        self._sel_next_btn = QPushButton(
            _("Download"))
        self._sel_next_btn.setObjectName("primary_btn")
        self._sel_import_btn.setObjectName("action_btn")
        btn_row.addWidget(self._sel_import_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._sel_cancel_btn)
        btn_row.addWidget(self._sel_next_btn)
        lyt.addLayout(btn_row)

        self._sel_cancel_btn.clicked.connect(self.reject)
        self._sel_next_btn.clicked.connect(self._on_select_next)
        self._sel_import_btn.clicked.connect(self._import_gguf_from_selection)

        # Pre-select active / default
        for eid, card in self._card_widgets.items():
            if eid == active_id:
                card["radio"].setChecked(True)
                break
        if not self._radio_group.checkedButton() and self._card_widgets:
            list(self._card_widgets.values())[0]["radio"].setChecked(True)

        return page

    def _build_model_card(self, entry: dict, t: dict, lang: str) -> dict:
        """Build one model card; return dict of widget refs."""
        from services.local_model_service import localize_field

        eid = entry.get("id", "")
        label = entry.get("label", eid.upper())
        size = entry.get("size_mb", 0)
        ram = entry.get("ram_gb", 0)
        desc = localize_field(entry, "desc", lang)
        pros = localize_field(entry, "pros", lang)

        frame = QGroupBox()
        frame.setObjectName("ai_model_card")
        fl = QVBoxLayout(frame)
        fl.setSpacing(4)
        fl.setContentsMargins(10, 8, 10, 8)

        # Top row: radio + label + size
        top_row = QHBoxLayout()
        radio = QRadioButton()
        lbl_name = QLabel(f"<b>{label}</b>")
        lbl_size = QLabel(f"  {size} MB  ·  RAM ≥ {ram} GB")
        lbl_size.setObjectName("muted")
        top_row.addWidget(radio)
        top_row.addWidget(lbl_name)
        top_row.addWidget(lbl_size)
        top_row.addStretch()
        fl.addLayout(top_row)

        # HuggingFace repo link (if present)
        hf_repo = entry.get("hf_repo", "")
        if hf_repo:
            hf_url = f"https://huggingface.co/{hf_repo}"
            hf_lbl = QLabel(f'<a href="{hf_url}">{hf_repo}</a>')
            hf_lbl.setOpenExternalLinks(True)
            hf_lbl.setObjectName("muted")
            fl.addWidget(hf_lbl)

        if desc:
            d = QLabel(desc)
            d.setWordWrap(True)
            d.setObjectName("muted")
            fl.addWidget(d)

        if pros:
            p = QLabel(pros)
            p.setWordWrap(True)
            fl.addWidget(p)

        # Status + delete row
        bot_row = QHBoxLayout()
        status_lbl = QLabel()
        status_lbl.setObjectName("muted")
        delete_btn = QPushButton(_("Delete"))
        delete_btn.setObjectName("action_btn")
        delete_btn.setFixedWidth(72)
        delete_btn.hide()
        bot_row.addWidget(status_lbl, 1)
        bot_row.addWidget(delete_btn)
        fl.addLayout(bot_row)

        delete_btn.clicked.connect(
            lambda _=False, _eid=eid: self._delete_model(_eid))

        return {
            "radio":      radio,
            "frame":      frame,
            "status_lbl": status_lbl,
            "delete_btn": delete_btn,
        }

    def _refresh_card_states(self) -> None:
        """Refresh all card status labels and delete-button visibility.

        Never raises: all service calls are guarded so a catalog/manifest
        error only results in 'Not downloaded' state for affected cards.
        """
        try:
            from services.local_model_service import (
                load_catalog, verify_model_file, load_manifest,
                get_models_dir, get_entry,
            )
            mdir     = get_models_dir()
            manifest = load_manifest(mdir)
            catalog  = load_catalog(mdir)
            ok_col   = "#2ecc71"
        except Exception:
            return   # can't refresh without service layer

        for entry in catalog:
            eid  = entry.get("id", "")
            card = self._card_widgets.get(eid)
            if not card:
                continue
            try:
                me    = get_entry(manifest, eid)
                fname = (me.get("file") or "").strip()
                path  = mdir / fname if fname else None
                if path and path.exists() and path.stat().st_size > 0:
                    if verify_model_file(mdir, eid):
                        card["status_lbl"].setText(
                            "✓  " + _("Ready"))
                        card["status_lbl"].setStyleSheet(
                            f"color:{ok_col};font-weight:600;")
                    else:
                        card["status_lbl"].setText(
                            _("Integrity failed"))
                        card["status_lbl"].setStyleSheet("color:#e03333;")
                    card["delete_btn"].show()
                else:
                    raise ValueError("not present")
            except Exception:
                card["status_lbl"].setText(
                    _("Not downloaded"))
                card["status_lbl"].setStyleSheet("")
                card["delete_btn"].hide()

    def _delete_model(self, entry_id: str) -> None:
        reply = QMessageBox.question(
            self,
            _("Delete Model"),
            _("Delete this model file? This cannot be undone."),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            from services.local_model_service import LocalModelService
            LocalModelService.get().delete_model(entry_id)
            LocalModelService.reset()
            self._refresh_card_states()
        except Exception as exc:
            QMessageBox.warning(self, msg(
                "settings_title", "Error"), str(exc))

    def _on_select_next(self) -> None:
        """Validate selection, handle conflict, start download."""
        from services.local_model_service import (
            load_catalog, verify_model_file, get_active_entry_id,
            load_manifest, get_entry, get_models_dir, set_active_entry,
        )
        # Which radio is checked?
        checked = self._radio_group.checkedButton()
        sel_id = None
        for eid, card in self._card_widgets.items():
            if card["radio"] is checked:
                sel_id = eid
                break
        if sel_id is None:
            return
        self._sel_id = sel_id

        mdir = get_models_dir()
        manifest = load_manifest(mdir)
        entry = get_entry(manifest, sel_id)
        path = mdir / entry.get("file", "")

        # Already downloaded and verified?
        if path.exists() and path.stat().st_size > 0:
            if verify_model_file(mdir, sel_id):
                QMessageBox.information(
                    self,
                    _("Download Local Model"),
                    _("This model is already downloaded and ready."),
                )
                self.accept()
                return

        # Conflict: a *different* verified model exists
        active_id = get_active_entry_id(mdir)
        if active_id != sel_id and verify_model_file(mdir, active_id):
            reply = QMessageBox.question(
                self,
                _("Switch Model"),
                msg("local_model_switch_confirm",
                      "A different model is already downloaded.  "
                      "It will be deleted before downloading the new one.  Continue?"),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
            try:
                from services.local_model_service import LocalModelService
                LocalModelService.get().delete_model(active_id)
                LocalModelService.reset()
            except Exception as exc:
                QMessageBox.warning(self, msg(
                    "settings_title", "Error"), str(exc))
                return

        set_active_entry(sel_id, mdir)
        self._show_page(self.PAGE_DOWNLOAD)
        self._start_download()

    # ── Page 1: download progress ────────────────────────────────────────────

    def _build_download_page(self, t: dict) -> QWidget:
        page = QWidget()
        lyt = QVBoxLayout(page)
        lyt.setContentsMargins(16, 16, 16, 16)
        lyt.setSpacing(10)

        self._dl_model_lbl = QLabel()
        lf = QFont()
        lf.setBold(True)
        self._dl_model_lbl.setFont(lf)
        lyt.addWidget(self._dl_model_lbl)

        hint = QLabel(msg(
            "local_model_download_hint",
            "Downloading…  You may cancel at any time; "
            "the download will resume from where it left off.",
        ))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        lyt.addWidget(hint)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(True)
        self._progress.setFormat("%p%")
        self._progress.setStyleSheet(
            progress_bar_qss(self._accent_color, self._dark)
        )
        lyt.addWidget(self._progress)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("monospace", 9))
        lyt.addWidget(self._log, 1)

        btn_row = QHBoxLayout()
        self._retry_btn = QPushButton(_("Retry"))
        self._action_btn = QPushButton(_("Cancel"))
        self._retry_btn.setObjectName("action_btn")
        self._retry_btn.hide()
        btn_row.addWidget(self._retry_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._action_btn)
        lyt.addLayout(btn_row)

        self._action_btn.clicked.connect(self._cancel)
        self._retry_btn.clicked.connect(self._retry_download)

        return page

    # ── Download control ─────────────────────────────────────────────────────

    def _start_download(self) -> None:
        from services.local_model_service import load_catalog
        eid = self._sel_id or ""
        cat = load_catalog()
        entry = next((e for e in cat if e.get("id") == eid),
                     cat[0] if cat else {})
        label = entry.get("label", eid.upper())

        self._dl_model_lbl.setText(label)
        self._retry_btn.hide()
        self._action_btn.setText(_("Cancel"))
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self._cancel)
        self._progress.setValue(0)
        self._progress.setFormat("0%")
        self._last_status_key = ""           # dedup guard

        bridge = self._bridge  # captured for the callbacks

        # Callbacks emit Qt signals directly — queued connection handles
        # cross-thread delivery to the main event loop.
        from services.download_controller import DownloadController
        DownloadController.get().start(
            entry_id=eid,
            progress_cb=lambda d, total: bridge.progress.emit(d, total),
            status_cb=lambda key: bridge.status.emit(key),
            done_cb=lambda _path: bridge.done.emit(),
            error_cb=lambda msg: bridge.error.emit(msg),
        )

    def _cancel(self) -> None:
        from services.download_controller import DownloadController
        DownloadController.get().cancel()
        self.reject()

    def _retry_download(self) -> None:
        self._retry_btn.hide()
        self._action_btn.setText(_("Cancel"))
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self._cancel)
        self._progress.setValue(0)
        self._progress.setFormat("0%")
        # Reset controller so a fresh download can start
        from services.download_controller import DownloadController
        DownloadController.reset()
        self._start_download()

    # ── Signal slots (main thread) ───────────────────────────────────────────

    def _on_progress(self, downloaded: object, total: object) -> None:
        try:
            dl  = int(downloaded)
            tot = int(total)
        except (TypeError, ValueError, OverflowError):
            return
        if tot > 0:
            pct    = min(100, int(dl * 100 / tot))
            dl_mb  = dl  / 1_048_576
            tot_mb = tot / 1_048_576
            self._progress.setValue(pct)
            fmt = _("{0:.0f} / {1:.0f} MB")
            try:
                self._progress.setFormat(
                    f"{fmt.format(dl_mb, tot_mb)}  {pct}%")
            except Exception:
                self._progress.setFormat(f"{pct}%")

    def _on_status(self, key: str) -> None:
        # Deduplicate: skip if same key received consecutively
        if getattr(self, "_last_status_key", "") == key:
            return
        self._last_status_key = key
        if key in ("download_dialog_model_hash_ok", "download_model_status_ready"):
            return   # these appear as part of the done message; skip log noise
        text = msg(key, key)
        if text:
            self._log_append(text)

    def _on_done(self) -> None:
        self._progress.setValue(100)
        self._progress.setFormat("100%")
        self._log_append(
            _("✓  Integrity verified"))
        self._retry_btn.hide()
        # ── Button becomes "Done / 完成" ──
        self._action_btn.setText(_("Done"))
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self.accept)
        # Reset singleton so next inference picks up the new file.
        from services.local_model_service import LocalModelService
        LocalModelService.reset()

    def _on_error(self, message: str) -> None:
        display = msg(message, message)
        self._log_append(
            f"\n[{_("Integrity check failed — file may be corrupted")}] {display}")
        self._retry_btn.show()
        self._action_btn.setText(_("Close"))
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self.reject)

    # ── Import from selection page ───────────────────────────────────────────

    def _import_gguf_from_selection(self) -> None:
        """Let user import a .gguf file from disk.

        Files matching a known catalog entry use that entry's canonical name.
        Unknown files create a new catalog+manifest entry under their own name.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            _("Import .gguf"),
            "",
            "GGUF files (*.gguf);;All files (*)",
        )
        if not path:
            return
        try:
            from services.local_model_service import (
                LocalModelService, get_active_entry_id,
            )
            svc = LocalModelService.get()
            # "__new__" forces catalog-lookup-by-filename / create-new behaviour
            dest = svc.import_gguf(path, "__new__")
            LocalModelService.reset()
            self._refresh_card_states()
            # Rebuild cards to show any newly added catalog entry
            self._rebuild_cards_if_needed()
            QMessageBox.information(
                self,
                _("Download Local Model"),
                _("✓  Model imported"),
            )
        except Exception as exc:
            QMessageBox.warning(
                self, _("Settings"), str(exc))

    def _rebuild_cards_if_needed(self) -> None:
        """Refresh card list if catalog has grown since dialog was opened."""
        from services.local_model_service import load_catalog
        current_ids = set(self._card_widgets.keys())
        catalog_ids = {e.get("id") for e in load_catalog()}
        if catalog_ids - current_ids:
            # New entries exist — close and let the caller re-open to rebuild.
            # (Full in-place rebuild is complex; a simple close is sufficient.)
            self.accept()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _show_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _log_append(self, text: str) -> None:
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
