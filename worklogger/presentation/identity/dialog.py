"""Linked identity management dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QToolButton,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.viewmodels import (
    IdentityManagementState,
    IdentityManagementViewModel,
)
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets.processing_progress import ProcessingProgress
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.identity_authorization import IdentityAuthorizationRequest
from worklogger.presentation.identity.dialogs import IdentityConfigurationDialog


class IdentityDialog(QDialog):
    def __init__(
        self,
        view_model: IdentityManagementViewModel,
        parent: QWidget | None = None,
        *, configuration=None, job_runner=None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._state: IdentityManagementState | None = None
        self._last_error: AppError | None = None
        self._configuration = configuration
        self._authorization_request = IdentityAuthorizationRequest(self, job_runner=job_runner)
        self._pending_close = None
        self.setObjectName("identity_dialog")
        self.setWindowTitle(_("Linked identities"))
        apply_window_icon(self)
        self._build_ui()
        self.resize(640, 420)
        self.setMinimumWidth(520)
        self._authorization_request.started.connect(lambda: self._set_busy(True))
        self._authorization_request.finished.connect(lambda: self._set_busy(False))

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    @property
    def state(self) -> IdentityManagementState | None:
        return self._state

    def refresh(self) -> bool:
        return self._set_state_result(self._view_model.load())

    def link_selected_provider(self) -> bool:
        provider = str(self.provider_combo.currentData() or "")
        if not provider:
            self.status_label.setText(_("Select a provider first."))
            return False
        def complete(result):
            self._set_state_result(result)
            if self._pending_close is not None:
                self.done(self._pending_close)
        return self._authorization_request.start(lambda token: self._view_model.link(provider, cancellation=token),
            on_complete=complete)

    def unlink_selected_identity(self) -> bool:
        if self._authorization_request.is_running:
            return False
        item = self.identity_list.currentItem()
        if item is None:
            self.status_label.setText(_("Select an identity first."))
            return False
        identity_id = int(item.data(256))
        return self._set_state_result(self._view_model.unlink(identity_id))

    def done(self, result):
        if self._authorization_request.is_running:
            self._pending_close = result
            self._authorization_request.cancel()
            return
        super().done(result)

    def _set_busy(self, busy):
        self.provider_combo.setEnabled(not busy)
        self.identity_list.setEnabled(not busy)
        self.configure_button.setEnabled(not busy and self._configuration is not None)
        self.unlink_button.setEnabled(not busy and self.identity_list.currentItem() is not None)
        if busy:
            self.link_button.setEnabled(False)
            self.processing_progress.start(_("Complete sign-in in your browser..."))
        else:
            self.processing_progress.finish()
            self._update_provider()

    def _update_provider(self):
        if self._authorization_request.is_running:
            return
        key = self.provider_combo.currentData()
        provider = next((p for p in self._state.providers if p.provider == key), None) if self._state else None
        self.link_button.setEnabled(bool(provider and provider.available))
        self.link_button.setToolTip("" if provider and provider.available else _("Configure this sign-in provider before continuing."))

    def _configure(self):
        provider = str(self.provider_combo.currentData() or "")
        if provider and self._configuration is not None:
            IdentityConfigurationDialog(self._configuration, provider, self).exec()
            self.refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.identity_list = QListWidget()
        self.identity_list.setObjectName("identity_list_widget")
        root.addWidget(self.identity_list, 1)

        link_row = QHBoxLayout()
        self.provider_combo = QComboBox()
        self.link_button = QPushButton(_("Link"))
        self.unlink_button = QPushButton(_("Unlink"))
        link_row.addWidget(self.provider_combo, 1)
        self.configure_button = QToolButton()
        self.configure_button.setObjectName("configure_identity_button")
        self.configure_button.setFixedSize(36, 36)
        self.configure_button.setToolTip(_("Configure sign-in"))
        self.configure_button.setAccessibleName(_("Configure sign-in"))
        set_button_icon(self.configure_button, "settings")
        self.configure_button.setEnabled(self._configuration is not None)
        self.configure_button.clicked.connect(self._configure)
        link_row.addWidget(self.configure_button)
        link_row.addWidget(self.link_button)
        link_row.addWidget(self.unlink_button)
        root.addLayout(link_row)
        self.processing_progress = ProcessingProgress()
        self.processing_progress.cancel_requested.connect(self._authorization_request.cancel)
        root.addWidget(self.processing_progress)

        bottom = QHBoxLayout()
        self.status_label = StatusLabel()
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addStretch()
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.link_button.clicked.connect(self.link_selected_provider)
        self.unlink_button.clicked.connect(self.unlink_selected_identity)
        self.close_button.clicked.connect(self.accept)
        self.provider_combo.currentIndexChanged.connect(self._update_provider)
        self.identity_list.currentRowChanged.connect(lambda: self.unlink_button.setEnabled(
            not self._authorization_request.is_running and self.identity_list.currentItem() is not None))

    def _set_state_result(self, result: object) -> bool:
        if not getattr(result, "ok", False) or getattr(result, "value", None) is None:
            self._set_error(getattr(result, "error", None))
            return False
        self._state = result.value
        self._render()
        self._last_error = None
        self.status_label.setText(self._state.message)
        return True

    def _render(self) -> None:
        self.identity_list.clear()
        self.provider_combo.clear()
        if self._state is None:
            return
        for identity in self._state.identities:
            label = identity.provider
            if identity.email:
                label = f"{label} | {identity.email}"
            elif identity.display_name:
                label = f"{label} | {identity.display_name}"
            item = QListWidgetItem(label)
            item.setData(256, identity.id)
            self.identity_list.addItem(item)
        for provider in self._state.providers:
            label = provider.display_name
            if not provider.available:
                status = _("Off") if provider.configured else _("Not configured")
                label = f"{label} ({status})"
            self.provider_combo.addItem(label, provider.provider)
        self._update_provider()
        self.unlink_button.setEnabled(self.identity_list.currentItem() is not None)

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(display_error_message(error))
