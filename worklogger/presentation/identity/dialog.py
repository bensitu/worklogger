"""Linked identity management dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels import (
    IdentityManagementState,
    IdentityManagementViewModel,
)


class IdentityDialog(QDialog):
    def __init__(
        self,
        view_model: IdentityManagementViewModel,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._state: IdentityManagementState | None = None
        self._last_error: AppError | None = None
        self.setObjectName("identity_dialog")
        self.setWindowTitle(_("Linked identities"))
        self._build_ui()

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
        return self._set_state_result(self._view_model.link(provider))

    def unlink_selected_identity(self) -> bool:
        item = self.identity_list.currentItem()
        if item is None:
            self.status_label.setText(_("Select an identity first."))
            return False
        identity_id = int(item.data(256))
        return self._set_state_result(self._view_model.unlink(identity_id))

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.identity_list = QListWidget()
        self.identity_list.setObjectName("identity_list")
        root.addWidget(self.identity_list, 1)

        link_row = QHBoxLayout()
        self.provider_combo = QComboBox()
        self.link_button = QPushButton(_("Link"))
        self.unlink_button = QPushButton(_("Unlink"))
        link_row.addWidget(self.provider_combo, 1)
        link_row.addWidget(self.link_button)
        link_row.addWidget(self.unlink_button)
        root.addLayout(link_row)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.link_button.clicked.connect(self.link_selected_provider)
        self.unlink_button.clicked.connect(self.unlink_selected_identity)
        self.close_button.clicked.connect(self.accept)

    def _set_state_result(self, result: object) -> bool:
        if not getattr(result, "ok", False) or getattr(result, "value", None) is None:
            self._set_error(getattr(result, "error", None))
            return False
        self._state = result.value
        self._render()
        self.status_label.setText(self._state.message or _("Ready"))
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
                label = f"{label} ({_('Not configured')})"
            self.provider_combo.addItem(label, provider.provider)

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(error.message if error is not None else _("Unknown error"))
