from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QApplication,
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

from config.constants import PASSWORD_MIN_LENGTH
from utils.formatters import format_timestamp_for_display
from utils.i18n import _, msg


class ChangePasswordDialog(QDialog):
    def __init__(
        self,
        auth_service,
        *,
        current_user_id: int | None = None,
        username: str = "",
        require_old_password: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._auth = auth_service
        self._current_user_id = current_user_id
        self._require_old_password = bool(require_old_password)
        self.setWindowTitle(_("Change Password"))
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        hint = QLabel(msg("change_password_recovery_key_warning"))
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        root.addWidget(hint)

        form = QFormLayout()
        self._username = QLineEdit()
        self._username.setText(username)
        if current_user_id is not None:
            self._username.hide()
        self._old = QLineEdit()
        self._new = QLineEdit()
        self._confirm = QLineEdit()
        for edit in (self._old, self._new, self._confirm):
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        if current_user_id is None:
            form.addRow(_("Username"), self._username)
        if self._require_old_password:
            form.addRow(_("Old Password"), self._old)
        form.addRow(_("New Password"), self._new)
        form.addRow(_("Confirm Password"), self._confirm)
        root.addLayout(form)

        row = QHBoxLayout()
        cancel_btn = QPushButton(_("Cancel"))
        save_btn = QPushButton(_("Save"))
        save_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(cancel_btn)
        row.addWidget(save_btn)
        root.addLayout(row)

        cancel_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._change)
        self._confirm.returnPressed.connect(self._change)

    def _change(self) -> None:
        old_pw = self._old.text()
        new_pw = self._new.text()
        confirm = self._confirm.text()
        if len(new_pw) < PASSWORD_MIN_LENGTH:
            QMessageBox.warning(
                self,
                _("Change Password"),
                _("Password must be at least 8 characters."),
            )
            return
        if new_pw != confirm:
            QMessageBox.warning(
                self,
                _("Change Password"),
                _("Passwords do not match."),
            )
            return
        try:
            if self._current_user_id is not None and not self._require_old_password:
                new_recovery_key = self._auth.force_change_password(
                    self._current_user_id,
                    new_pw,
                )
            elif self._current_user_id is not None:
                new_recovery_key = self._auth.change_password(
                    self._current_user_id,
                    old_pw,
                    new_pw,
                )
            else:
                username = self._username.text().strip()
                if not username:
                    QMessageBox.warning(
                        self,
                        _("Change Password"),
                        _("Username is required."),
                    )
                    return
                new_recovery_key = self._auth.change_password_for_username(
                    username,
                    old_pw,
                    new_pw,
                )
        except ValueError:
            QMessageBox.warning(
                self,
                _("Change Password"),
                _("Password must be at least 8 characters."),
            )
            return
        if not new_recovery_key:
            warning = (
                _("Old password is incorrect.")
                if self._require_old_password
                else _("Password change failed.")
            )
            QMessageBox.warning(
                self,
                _("Change Password"),
                warning,
            )
            return
        self._show_recovery_key(str(new_recovery_key))
        self.accept()

    def _show_recovery_key(self, recovery_key: str) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(_("Change Password"))
        dlg.setMinimumWidth(500)
        generated_at = format_timestamp_for_display(
            datetime.now(timezone.utc).isoformat(timespec="seconds")
        )

        root = QVBoxLayout(dlg)
        info = QLabel(msg("new_recovery_key_after_password_change"))
        info.setWordWrap(True)
        root.addWidget(info)

        form = QFormLayout()
        generated_edit = QLineEdit(generated_at)
        generated_edit.setReadOnly(True)
        key_edit = QLineEdit(recovery_key)
        key_edit.setReadOnly(True)
        form.addRow(_("Generated At"), generated_edit)
        form.addRow(_("Recovery Key"), key_edit)
        root.addLayout(form)

        status_lbl = QLabel("")
        status_lbl.setObjectName("muted")
        root.addWidget(status_lbl)

        row = QHBoxLayout()
        copy_btn = QPushButton(_("Copy"))
        save_as_btn = QPushButton(_("Save As"))
        ok_btn = QPushButton(_("OK"))
        ok_btn.setObjectName("primary_btn")
        row.addStretch()
        row.addWidget(copy_btn)
        row.addWidget(save_as_btn)
        row.addWidget(ok_btn)
        root.addLayout(row)

        def _copy_key() -> None:
            QApplication.clipboard().setText(recovery_key)
            status_lbl.setText(_("Copied!"))

        def _save_key() -> None:
            path, _dialog_filter = QFileDialog.getSaveFileName(
                dlg,
                _("Save Recovery Key"),
                "worklogger-recovery-key.txt",
                _("Text Files (*.txt)"),
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(f"{_('Generated At')}: {generated_at}\n")
                    fh.write(f"{_('Recovery Key')}: {recovery_key}\n")
                    fh.write("\n")
                    fh.write(msg("new_recovery_key_after_password_change"))
                    fh.write("\n")
            except OSError:
                QMessageBox.warning(
                    dlg,
                    _("Change Password"),
                    _("Could not save recovery key."),
                )
                return
            status_lbl.setText(_("Recovery key saved."))

        copy_btn.clicked.connect(_copy_key)
        save_as_btn.clicked.connect(_save_key)
        ok_btn.clicked.connect(dlg.accept)
        dlg.exec()
