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
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QTextEdit, QMessageBox, QFileDialog,
    QButtonGroup, QRadioButton, QGroupBox, QScrollArea, QWidget,
    QFrame, QStackedWidget,
)
from PySide6.QtGui import QFont

from utils.i18n import _, msg
from config.themes import (
    DEFAULT_CUSTOM_COLOR,
    LOCAL_MODEL_READY_COLOR,
    apply_widget_qss,
    clear_widget_qss,
    progress_bar_qss,
    status_label_qss,
)


# Cross-thread bridge.

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


# LocalDownloadDialog two-page flow.

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
                 accent_color: str = DEFAULT_CUSTOM_COLOR,
                 dark: bool = False,
                 on_model_changed: Optional[Callable[[str, str], None]] = None,
                 catalog_override: Optional[list[dict]] = None,
                 services=None) -> None:
        super().__init__(parent)
        self._lang = lang
        self._accent_color = accent_color
        self._dark = dark
        self._on_model_changed = on_model_changed
        self._catalog_override = catalog_override
        self._services = services
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
        self._stack.addWidget(self._build_select_page(_))
        self._stack.addWidget(self._build_download_page(_))

        self._bridge.progress.connect(self._on_progress)
        self._bridge.status.connect(self._on_status)
        self._bridge.done.connect(self._on_done)
        self._bridge.error.connect(self._on_error)

        self._show_page(self.PAGE_SELECT)

    def _build_select_page(self, _: dict) -> QWidget:
        from services.local_model_service import (
            ensure_catalog, load_catalog, get_active_entry_id,
            get_models_dir,
        )
        # Ensure the writable models directory exists before import/download.
        try:
            ensure_catalog(get_models_dir())
        except Exception:
            pass
        catalog   = self._catalog_override if self._catalog_override is not None else load_catalog()
        active_id = get_active_entry_id(services=self._services)

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
            "Each user can select one active local model. Downloaded GGUF files are shared across users.",
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
            card = self._build_model_card(entry, _, lang)
            self._card_widgets[eid] = card
            self._radio_group.addButton(card["radio"])
            cards_l.addWidget(card["frame"])

        if not catalog:
            empty_lbl = QLabel(
                msg(
                    "local_model_no_downloadable_models",
                    "No downloadable models are available. You can still import a local .gguf file.",
                )
            )
            empty_lbl.setWordWrap(True)
            empty_lbl.setObjectName("muted")
            empty_lbl.setAlignment(Qt.AlignCenter)
            cards_l.addWidget(empty_lbl, 1)

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
        self._radio_group.buttonToggled.connect(
            lambda _button, _checked: self._sync_select_next_button()
        )

        # Preselect active entry, then fallback to first card.
        for eid, card in self._card_widgets.items():
            if eid == active_id:
                card["radio"].setChecked(True)
                break
        if not self._radio_group.checkedButton() and self._card_widgets:
            list(self._card_widgets.values())[0]["radio"].setChecked(True)
        self._sync_select_next_button()

        return page

    def _build_model_card(self, entry: dict, t: dict, lang: str) -> dict:
        """Build one model card; return dict of widget refs."""
        from services.local_model_service import localize_field

        eid = entry.get("id", "")
        label = entry.get("display_name", eid.upper())
        size = entry.get("estimated_size_mb", 0)
        ram = entry.get("min_ram_gb", 0)
        desc = localize_field(entry, "description", lang)
        status = str(entry.get("status", "")).strip()

        frame = QGroupBox()
        frame.setObjectName("ai_model_card")
        fl = QVBoxLayout(frame)
        fl.setSpacing(4)
        fl.setContentsMargins(10, 8, 10, 8)

        top_row = QHBoxLayout()
        radio = QRadioButton()
        lbl_name = QLabel(f"<b>{label}</b>")
        lbl_size = QLabel(
            _("  {size} MB  ·  RAM ≥ {ram} GB").format(size=size, ram=ram)
        )
        lbl_size.setObjectName("muted")
        top_row.addWidget(radio)
        top_row.addWidget(lbl_name)
        top_row.addWidget(lbl_size)
        top_row.addStretch()
        fl.addLayout(top_row)

        status_text = self._status_badge_text(status)
        if status_text:
            status_badge = QLabel(status_text)
            status_badge.setObjectName("muted")
            fl.addWidget(status_badge)

        hf_repo = entry.get("repo_id", "")
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

    @staticmethod
    def _status_badge_text(status: str) -> str:
        mapping = {
            "experimental": _("Experimental"),
            "local": _("Local model"),
            "preserved": _("Preserved local model"),
        }
        return mapping.get(status, "")

    def _refresh_card_states(self) -> None:
        """Refresh all card status labels and delete-button visibility.

        Never raises: all service calls are guarded so a catalog/manifest
        error only results in 'Not downloaded' state for affected cards.
        """
        ok_col = LOCAL_MODEL_READY_COLOR
        try:
            from services.local_model_service import (
                load_catalog, verify_model_file, load_manifest,
                get_models_dir, get_entry, get_active_entry_id,
                list_users_using_model,
            )
            mdir     = get_models_dir()
            manifest = load_manifest(mdir)
            catalog  = load_catalog(mdir)
            active_id = get_active_entry_id(mdir, services=self._services)
            current_user_id = int(getattr(self._services, "current_user_id", 0) or 0)
        except Exception:
            return

        for entry in catalog:
            eid  = entry.get("id", "")
            card = self._card_widgets.get(eid)
            if not card:
                continue
            try:
                me    = get_entry(manifest, eid, services=self._services, models_dir=mdir)
                fname = (me.get("filename") or "").strip()
                path  = mdir / fname if fname else None
                if path and path.exists() and path.stat().st_size > 0:
                    if verify_model_file(mdir, eid):
                        state = _("Active") if eid == active_id else _("Ready")
                        users = set(list_users_using_model(self._services, eid))
                        if users - {current_user_id}:
                            used_text = _("Used by another user")
                            state = f"{state} · {used_text}"
                        card["status_lbl"].setText(f"✓  {state}")
                        apply_widget_qss(
                            card["status_lbl"],
                            status_label_qss("success", ok_col),
                        )
                    else:
                        card["status_lbl"].setText(
                            _("Integrity failed"))
                        apply_widget_qss(
                            card["status_lbl"], status_label_qss("error"))
                    card["delete_btn"].show()
                else:
                    raise ValueError("not present")
            except Exception:
                card["status_lbl"].setText(
                    _("Not downloaded"))
                clear_widget_qss(card["status_lbl"])
                card["delete_btn"].hide()
        self._sync_select_next_button()

    def _remove_cards_missing_from_catalog(self) -> bool:
        """Remove card widgets for local entries pruned from the catalog."""
        try:
            from services.local_model_service import load_catalog
            catalog_ids = {
                str(entry.get("id", "")).strip()
                for entry in load_catalog()
                if str(entry.get("id", "")).strip()
            }
        except Exception:
            return False

        selected_id = self._selected_entry_id()
        removed_selected = False
        changed = False
        for eid in list(self._card_widgets.keys()):
            if eid in catalog_ids:
                continue
            card = self._card_widgets.pop(eid)
            radio = card.get("radio")
            if radio is not None:
                self._radio_group.removeButton(radio)
            frame = card.get("frame")
            if frame is not None:
                frame.hide()
                frame.setParent(None)
                frame.deleteLater()
            removed_selected = removed_selected or eid == selected_id
            changed = True

        if removed_selected and self._card_widgets:
            first_card = next(iter(self._card_widgets.values()))
            first_card["radio"].setChecked(True)
        return changed

    def _selected_entry_id(self) -> str | None:
        checked = self._radio_group.checkedButton()
        if checked is None:
            return None
        for eid, card in self._card_widgets.items():
            if card["radio"] is checked:
                return eid
        return None

    def _is_entry_downloaded(self, entry_id: str) -> bool:
        try:
            from services.local_model_service import (
                get_entry, get_models_dir, load_manifest,
            )
            mdir = get_models_dir()
            entry = get_entry(load_manifest(mdir), entry_id, services=self._services, models_dir=mdir)
            filename = str(entry.get("filename", "")).strip()
            path = mdir / filename if filename else None
            return bool(path) and path.exists() and path.stat().st_size > 0
        except Exception:
            return False

    def _sync_select_next_button(self) -> None:
        if not hasattr(self, "_sel_next_btn"):
            return
        entry_id = self._selected_entry_id()
        active_id = ""
        try:
            from services.local_model_service import get_active_entry_id
            active_id = get_active_entry_id(services=self._services)
        except Exception:
            active_id = ""
        downloaded = bool(entry_id) and self._is_entry_downloaded(str(entry_id))
        enabled = bool(entry_id) and not (downloaded and entry_id == active_id)
        self._sel_next_btn.setEnabled(enabled)
        self._sel_next_btn.setText(_("Select") if downloaded else _("Download"))
        if enabled:
            self._sel_next_btn.setToolTip("")
        elif not entry_id:
            self._sel_next_btn.setToolTip(
                msg(
                    "local_model_no_downloadable_models",
                    "No downloadable models are available. You can still import a local .gguf file.",
                )
            )
        else:
            self._sel_next_btn.setToolTip(_("This model is already selected and ready."))

    def _delete_model(self, entry_id: str) -> None:
        try:
            from services.local_model_service import list_users_using_model
            current_user_id = int(getattr(self._services, "current_user_id", 0) or 0)
            users = set(list_users_using_model(self._services, entry_id))
            if users - {current_user_id}:
                QMessageBox.warning(
                    self,
                    _("Delete Model"),
                    _("This model is used by another user and cannot be deleted."),
                )
                return
        except Exception:
            pass

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
            from services.local_model_service import (
                LocalModelService,
                clear_active_model_id_for_user,
                get_active_entry_id,
            )
            active_id = get_active_entry_id(services=self._services)
            if active_id == entry_id:
                clear_active_model_id_for_user(self._services)
            LocalModelService.get().delete_model(entry_id, services=self._services)
            LocalModelService.reset()
            self._remove_cards_missing_from_catalog()
            self._refresh_card_states()
            if callable(self._on_model_changed):
                try:
                    self._on_model_changed("deleted", entry_id)
                except Exception:
                    pass
        except Exception as exc:
            QMessageBox.warning(self, msg(
                "settings_title", "Error"), str(exc))

    def _verify_failure_text(self, reason: str) -> str:
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
        return mapping.get(
            reason,
            msg(
                "local_model_verify_failed",
                "Local model verification failed. Please re-download or switch model.",
            ),
        )

    def _verify_selected_before_close(self, models_dir: Path, entry_id: str) -> bool:
        from services.local_model_service import verify_model_file_with_reason
        ok, reason = verify_model_file_with_reason(
            models_dir,
            entry_id,
            timeout_s=5.0,
            retries=1,
            services=self._services,
        )
        if ok:
            return True
        QMessageBox.warning(
            self,
            _("Download Local Model"),
            self._verify_failure_text(reason),
        )
        return False

    def _finish_after_download(self) -> None:
        from services.local_model_service import get_active_entry_id, get_models_dir
        mdir = get_models_dir()
        entry_id = self._sel_id or get_active_entry_id(mdir, services=self._services)
        if not entry_id:
            self.accept()
            return
        if not self._verify_selected_before_close(mdir, entry_id):
            return
        self.accept()

    def _on_select_next(self) -> None:
        """Validate selection, handle conflict, start download."""
        from services.local_model_service import (
            load_manifest, get_entry, get_models_dir, set_active_entry,
        )
        sel_id = self._selected_entry_id()
        if sel_id is None:
            return
        self._sel_id = sel_id

        mdir = get_models_dir()
        manifest = load_manifest(mdir)
        entry = get_entry(manifest, sel_id, services=self._services, models_dir=mdir)
        path = mdir / entry.get("filename", "")

        if path.exists() and path.stat().st_size > 0:
            if self._verify_selected_before_close(mdir, sel_id):
                set_active_entry(sel_id, mdir, services=self._services)
                if callable(self._on_model_changed):
                    try:
                        self._on_model_changed("selected", sel_id)
                    except Exception:
                        pass
                QMessageBox.information(
                    self,
                    _("Download Local Model"),
                    _("This model is already downloaded and ready."),
                )
                self.accept()
            return

        self._show_page(self.PAGE_DOWNLOAD)
        self._start_download()

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
        apply_widget_qss(
            self._progress,
            progress_bar_qss(self._accent_color, self._dark),
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

    def _start_download(self) -> None:
        from services.local_model_service import load_catalog
        eid = self._sel_id or ""
        cat = load_catalog()
        entry = next((e for e in cat if e.get("id") == eid),
                     cat[0] if cat else {})
        label = entry.get("display_name", eid.upper())

        self._dl_model_lbl.setText(label)
        self._retry_btn.hide()
        self._action_btn.setText(_("Cancel"))
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self._cancel)
        self._progress.setValue(0)
        self._progress.setFormat("0%")
        self._last_status_key = ""

        bridge = self._bridge

        # Emit bridge signals directly; Qt queues cross-thread delivery.
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
        # Reset controller state before starting a fresh retry.
        from services.download_controller import DownloadController
        DownloadController.reset()
        self._start_download()

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
        # Skip repeated statuses to keep the log readable.
        if getattr(self, "_last_status_key", "") == key:
            return
        self._last_status_key = key
        if key in ("download_dialog_model_hash_ok", "download_model_status_ready"):
            return
        text = msg(key)
        if text:
            self._log_append(text)

    def _on_done(self) -> None:
        self._progress.setValue(100)
        self._progress.setFormat("100%")
        self._log_append(
            _("✓  Integrity verified"))
        self._retry_btn.hide()
        self._action_btn.setText(_("Done"))
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self._finish_after_download)
        # Ensure next inference picks up the newly downloaded model file.
        from services.local_model_service import LocalModelService, set_active_entry, get_models_dir
        try:
            if self._sel_id:
                set_active_entry(self._sel_id, get_models_dir(), services=self._services)
        except Exception:
            pass
        LocalModelService.reset()
        if callable(self._on_model_changed):
            try:
                self._on_model_changed("downloaded", str(self._sel_id or ""))
            except Exception:
                pass

    def _on_error(self, message: str) -> None:
        display = msg(message)
        error_title = _("Integrity check failed - file may be corrupted")
        self._log_append(
            f"\n[{error_title}] {display}")
        self._retry_btn.show()
        self._action_btn.setText(_("Close"))
        self._action_btn.clicked.disconnect()
        self._action_btn.clicked.connect(self.reject)

    def _import_gguf_from_selection(self) -> None:
        """Let user import a .gguf file from disk.

        Files matching a known catalog entry use that entry's canonical name.
        Unknown files create a new catalog+manifest entry under their own name.
        """
        path, _dialog_filter = QFileDialog.getOpenFileName(
            self,
            _("Import .gguf"),
            "",
            _("GGUF files (*.gguf);;All files (*)"),
        )
        if not path:
            return
        try:
            from services.local_model_service import LocalModelService
            svc = LocalModelService.get()
            # "__new__" always routes through filename matching or new-entry creation.
            imported = svc.import_gguf(path, "__new__", services=self._services)
            LocalModelService.reset()
            self._refresh_card_states()
            # New custom entries can add cards that were not present at dialog open.
            self._rebuild_cards_if_needed()
            if callable(self._on_model_changed):
                try:
                    self._on_model_changed("imported", imported.name)
                except Exception:
                    pass
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
            # Close so the caller can reopen with a fully rebuilt card list.
            self.accept()

    def _show_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _log_append(self, text: str) -> None:
        self._log.append(text)
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
