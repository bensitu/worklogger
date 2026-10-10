"""Desktop application registration settings for a selected identity provider."""

from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout
from worklogger.infrastructure.i18n import _
from worklogger.infrastructure.identity.config import ProviderRegistration
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.status_label import StatusLabel
from worklogger.presentation.widgets.icons import set_button_icon


class IdentityConfigurationDialog(QDialog):
    def __init__(self, store, provider, parent=None):
        super().__init__(parent)
        self._store, self._provider = store, provider
        self.setObjectName("identity_configuration_dialog")
        self.setWindowTitle(_("Configure sign-in") + " - " + provider.title())
        self.setMinimumWidth(540)
        apply_window_icon(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        description = QLabel(_("Use an application registration supplied by your distributor or administrator. This is not your account password."))
        description.setWordWrap(True)
        root.addWidget(description)
        form = QFormLayout()
        form.setSpacing(12)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.client_id_input = QLineEdit()
        self.client_id_input.setObjectName("identity_client_id_line_edit")
        self.client_id_input.setMaxLength(1024)
        self.client_id_input.setAccessibleName(_("Application client ID"))
        form.addRow(_("Application client ID"), self.client_id_input)
        self.tenant_input = QLineEdit()
        self.tenant_input.setObjectName("identity_tenant_line_edit")
        self.tenant_input.setMaxLength(1024)
        self.tenant_input.setAccessibleName(_("Microsoft tenant ID"))
        self.secret_input = QLineEdit()
        self.secret_input.setObjectName("identity_client_secret_line_edit")
        self.secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_input.setMaxLength(1024)
        self.secret_input.setAccessibleName(_("Desktop client secret (optional)"))
        if provider == "microsoft":
            form.addRow(_("Microsoft tenant ID"), self.tenant_input)
            self.secret_input.hide()
        else:
            form.addRow(_("Desktop client secret (optional)"), self.secret_input)
            self.tenant_input.hide()
        root.addLayout(form)
        self.status_label = StatusLabel()
        root.addWidget(self.status_label)
        row = QHBoxLayout()
        row.addStretch(1)
        close = QPushButton(_("Cancel"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_identity_configuration_button")
        self.save_button.setProperty("variant", "primary")
        self.save_button.setDefault(True)
        set_button_icon(self.save_button, "save")
        self.save_button.clicked.connect(self.save)
        row.addWidget(self.save_button)
        root.addLayout(row)
        loaded = store.load(provider)
        if loaded.ok:
            registration = loaded.value[0]
            self.client_id_input.setText(registration.client_id)
            self.tenant_input.setText(registration.tenant_id)
            self.secret_input.setText(registration.client_secret)
        else:
            self.status_label.setText(display_error_message(loaded.error))
        if store.managed(provider):
            for field in (self.client_id_input, self.tenant_input, self.secret_input):
                field.setReadOnly(True)
            self.save_button.setEnabled(False)
            self.status_label.setText(_("This sign-in configuration is managed outside the application."))

    def save(self):
        registration = ProviderRegistration(self.client_id_input.text().strip(),
            self.tenant_input.text().strip() if self._provider == "microsoft" else "",
            self.secret_input.text().strip() if self._provider == "google" else "")
        result = self._store.save(self._provider, registration)
        if result.ok:
            self.accept()
        else:
            self.status_label.setText(display_error_message(result.error))
