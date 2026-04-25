from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from utils.i18n import _


class RegisterDialog(QDialog):
    def __init__(self, auth_service, parent=None):
        super().__init__(parent)
        self._auth = auth_service
        self.username: str | None = None
        self.recovery_key: str = self._auth.generate_recovery_key()

        self.setWindowTitle(_("Register"))
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._username = QLineEdit()
        self._password = QLineEdit()
        self._confirm = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow(_("Username"), self._username)
        form.addRow(_("Password"), self._password)
        form.addRow(_("Confirm Password"), self._confirm)
        self._recovery_key = QLineEdit(self.recovery_key)
        self._recovery_key.setReadOnly(True)
        form.addRow(_("Recovery Key"), self._recovery_key)
        root.addLayout(form)

        hint = QLabel(
            _(
                "Copy and safely store this recovery key now. "
                "If it is lost, only an administrator can reset your password."
            )
        )
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)

        recovery_row = QHBoxLayout()
        copy_btn = QPushButton(_("Copy"))
        export_btn = QPushButton(_("Export"))
        recovery_row.addStretch()
        recovery_row.addWidget(copy_btn)
        recovery_row.addWidget(export_btn)
        root.addLayout(recovery_row)

        self._saved_recovery = QCheckBox(
            _("I have saved this recovery key safely.")
        )
        root.addWidget(self._saved_recovery)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        register_btn = QPushButton(_("Register"))
        register_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(register_btn)
        root.addLayout(row)

        copy_btn.clicked.connect(self._copy_recovery_key)
        export_btn.clicked.connect(self._export_recovery_key)
        cancel_btn.clicked.connect(self.reject)
        register_btn.clicked.connect(self._register)
        self._confirm.returnPressed.connect(self._register)

    def _copy_recovery_key(self) -> None:
        QApplication.clipboard().setText(self.recovery_key)

    def _export_recovery_key(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            _("Save Recovery Key"),
            "worklogger-recovery-key.txt",
            _("Text Files (*.txt)"),
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.recovery_key + "\n")
        except OSError:
            QMessageBox.warning(
                self,
                _("Register"),
                _("Could not save recovery key."),
            )
            return
        QMessageBox.information(
            self,
            _("Register"),
            _("Recovery key saved."),
        )

    def _register(self) -> None:
        username = self._username.text().strip()
        password = self._password.text()
        confirm = self._confirm.text()
        if not username:
            QMessageBox.warning(self, _("Register"), _("Username is required."))
            return
        if len(password) < 6:
            QMessageBox.warning(
                self,
                _("Register"),
                _("Password must be at least 6 characters."),
            )
            return
        if password != confirm:
            QMessageBox.warning(self, _("Register"), _("Passwords do not match."))
            return
        if not self._saved_recovery.isChecked():
            QMessageBox.warning(
                self,
                _("Register"),
                _("Please confirm that you have saved the recovery key."),
            )
            return
        try:
            self._auth.register(username, password, self.recovery_key)
        except ValueError as exc:
            if str(exc) == "username_exists":
                text = _("Username already exists.")
            else:
                text = _("Registration failed.")
            QMessageBox.warning(self, _("Register"), text)
            return
        self.username = username
        QMessageBox.information(
            self,
            _("Register"),
            _("Registration successful. Please log in."),
        )
        self.accept()
