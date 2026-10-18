"""Background cloud backup scheduling and explicit transfer confirmations."""

from datetime import datetime
from time import monotonic
from weakref import WeakSet

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QLineEdit, QMessageBox, QProgressBar, QVBoxLayout
from shiboken6 import isValid
from tzlocal import get_localzone

from worklogger.domain.cloud_backup import backup_due
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.job_runner import QtJobRunner, owned_callback


def _local_time(value):
    return datetime.fromisoformat(value).astimezone().strftime("%Y-%m-%d %H:%M") if value else ""


class BackupTransferDialog(QDialog):
    def __init__(self, overview, *, restore, parent=None, local_path=None):
        super().__init__(parent)
        self.setWindowTitle(_("Restore local recovery copy") if local_path else _("Download and restore") if restore else _("Upload backup"))
        self.setMinimumWidth(360)
        root = QVBoxLayout(self)
        versions = () if local_path else overview.versions
        latest = versions[0] if versions else None
        text = (_("Recovery file: {path}").format(path=local_path) if local_path else
            _("Latest cloud backup: {time}").format(time=_local_time(latest.created_at)) if latest else _("No cloud backups found."))
        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(label)
        self.versions = QComboBox()
        for version in versions:
            self.versions.addItem(_local_time(version.created_at) + " · " + version.revision[:12], version.revision)
        self.versions.setAccessibleName(_("Backup version"))
        self.versions.setVisible(restore and not local_path)
        root.addWidget(self.versions)
        if restore:
            warning = QLabel(_("Restoring replaces this account's portable data. Other accounts and login credentials are unchanged. A local recovery copy is saved first; sign in again afterwards."))
            warning.setWordWrap(True)
            root.addWidget(warning)
        self.force = QCheckBox(_("Replace current account data") if local_path else _("Overwrite despite version differences"))
        needs_force = True if local_path else overview.local_changed if restore else overview.remote_changed
        self.force.setVisible(needs_force)
        root.addWidget(self.force)
        self.passphrase = QLineEdit()
        self.passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase.setMaxLength(1024)
        self.passphrase.setPlaceholderText(_("Backup passphrase (blank uses the stored passphrase)"))
        self.passphrase.setAccessibleName(_("Backup passphrase"))
        self.passphrase.setVisible(restore)
        root.addWidget(self.passphrase)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.windowTitle())
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancel"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not needs_force)
        self.force.toggled.connect(lambda checked: buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(not needs_force or checked))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)


class RestoreProgressDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(_("Download and restore"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
        root = QVBoxLayout(self)
        root.addWidget(QLabel(_("Downloading and restoring personal data...")))
        progress = QProgressBar()
        progress.setRange(0, 0)
        root.addWidget(progress)

    def reject(self):
        pass

    def closeEvent(self, event):
        event.ignore()


class CloudBackupWorkflow(QObject):
    def __init__(self, service, *, startup_delay_seconds, check_interval_seconds=60,
                 retry_initial_seconds=300, retry_max_seconds=3600, job_runner=None):
        super().__init__()
        self.service = service
        self.runner = job_runner or QtJobRunner(self)
        self._panels = WeakSet()
        self._configuration, self._credentials, self._state = None, None, {}
        self._busy, self._loaded = False, False
        self._retry_at, self._failures = 0, 0
        self._owner = None
        self._last_notification = ""
        self._message = ""
        self._restore_handler = None
        self._confirming = False
        self._startup_delay_seconds = startup_delay_seconds
        self._retry_initial_seconds = retry_initial_seconds
        self._retry_max_seconds = retry_max_seconds
        self._startup_ready_at = float("inf")
        self._timer = QTimer(self)
        self._timer.setInterval(check_interval_seconds * 1000)
        self._timer.timeout.connect(self._tick)

    def start(self, owner):
        self.setParent(owner)
        self._owner = owner
        self._startup_ready_at = monotonic() + self._startup_delay_seconds
        self._timer.start()
        QTimer.singleShot(self._startup_delay_seconds * 1000, self, self.reload)

    def set_restore_handler(self, handler):
        self._restore_handler = handler

    def bind(self, panel):
        self._panels.add(panel)
        panel.save_requested.connect(lambda configuration, credentials: self._run(
            lambda: self.service.configure(configuration, credentials), success=_("Cloud backup settings saved."), configured=True))
        panel.test_requested.connect(lambda: self._run(self.service.test_connection, success=_("Connection verified.")))
        panel.upload_requested.connect(lambda: self._prepare(panel, restore=False))
        panel.restore_requested.connect(lambda: self._prepare(panel, restore=True))
        panel.local_restore_requested.connect(lambda: self._prepare_local(panel))
        if self._configuration is not None:
            panel.set_configuration(self._configuration, self._credentials)
        self._update()
        if not self._loaded:
            self.reload()

    def reload(self):
        self._run(lambda: Result.success(None), refresh=True)

    def _update(self):
        status = self._message
        if self._state.get("last_success"):
            status += ("\n" if status else "") + _("Last cloud backup: {time}").format(time=_local_time(self._state["last_success"]))
        if self._state.get("last_restore"):
            status += ("\n" if status else "") + _("Last restore: {time}").format(time=_local_time(self._state["last_restore"]))
        if self._state.get("last_error"):
            status += ("\n" if status else "") + display_error_message(ValidationError(self._state["last_error"], self._state["last_error"]))
        if self._state.get("pending_deletions"):
            status += ("\n" if status else "") + _("Some expired backups could not be removed. Cleanup will be retried.")
        for panel in tuple(self._panels):
            if isValid(panel):
                panel.set_busy(self._busy, configured=self._configuration is not None)
                panel.status_label.setText(_("Cloud backup operation in progress...") if self._busy else status)

    def _run(self, operation, *, success="", callback=None, configured=False, refresh=False, automatic=False):
        if self._busy:
            return
        self._busy = True
        self._update()
        def work(_token):
            result = operation()
            if not result.ok and not refresh:
                self.service.record_failure(result.error.code if result.error else "cloud_operation_failed")
            return result, self.service.settings()
        def complete(outer):
            self._busy = False
            result, settings = outer.value if outer.ok else (outer, Result.success(None))
            if settings.ok and settings.value is not None:
                self._configuration, self._credentials, self._state = settings.value
                self._loaded = True
                if (configured and result.ok) or refresh:
                    for panel in tuple(self._panels):
                        if isValid(panel) and self._configuration is not None and (configured and result.ok or not panel.has_unsaved_changes):
                            panel.set_configuration(self._configuration, self._credentials)
            if not settings.ok and result.ok and (refresh or configured):
                result = settings
            if result.ok:
                self._message = success
                self._failures, self._last_notification = 0, ""
                if not refresh:
                    self._retry_at = 0
            else:
                self._failures += 1
                self._retry_at = monotonic() + min(self._retry_max_seconds,
                    self._retry_initial_seconds * 2 ** min(self._failures - 1, 15))
                self._message = display_error_message(result.error)
                code = result.error.code if result.error else "cloud_operation_failed"
                if not automatic or code != self._last_notification:
                    self._notify(self._message)
                    self._last_notification = code
            self._update()
            if callback is not None:
                callback(result)
            if refresh or configured:
                self._tick()
        try:
            self.runner.submit("cloud_backup", work, on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError("cloud_operation_failed", "cloud_operation_failed")))

    def _notify(self, message):
        if self._owner is None or not isValid(self._owner):
            return
        residency = getattr(self._owner, "_residency_controller", None)
        if residency is not None and residency.notify_message(_("Personal cloud backup"), message, warning=True):
            return
        dialog = QMessageBox(QMessageBox.Icon.Warning, _("Personal cloud backup"), message, parent=self._owner)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def _prepare(self, panel, *, restore):
        if self._busy or panel.has_unsaved_changes:
            return
        if restore and not self._restore_allowed():
            self._message = _("Save or discard unsaved edits before restoring a cloud backup.")
            self._update()
            return
        def ready(result):
            if not result.ok or not isValid(panel):
                return
            if restore and not self._restore_allowed():
                self._message = _("Save or discard unsaved edits before restoring a cloud backup.")
                self._update()
                return
            overview = result.value
            if restore and not overview.versions:
                self._message = _("No cloud backups found.")
                self._update()
                return
            dialog = BackupTransferDialog(overview, restore=restore, parent=panel)
            self._confirming = True
            try:
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                latest = overview.versions[0].revision if overview.versions else ""
                if restore:
                    revision, force, passphrase = dialog.versions.currentData(), dialog.force.isChecked(), dialog.passphrase.text() or None
                    operation = lambda: self.service.download(revision, expected_revision=latest,
                        expected_local_digest=overview.local_digest, force=force, passphrase=passphrase)
                    self._restore(panel, operation)
                else:
                    force = dialog.force.isChecked()
                    self._run(lambda: self.service.upload(expected_revision=latest, force=force), success=_("Cloud backup uploaded."))
            finally:
                self._confirming = False
                dialog.deleteLater()
        self._run(self.service.overview, callback=ready)

    def _restore(self, panel, operation):
        if not self._restore_allowed():
            return
        progress = RestoreProgressDialog(panel.window())
        progress.show()
        def restored(value):
            progress.accept()
            progress.deleteLater()
            if value.ok:
                QMessageBox.information(panel, _("Download and restore"),
                    _("Data restored. Recovery copy: {path}").format(path=value.value.recovery_path))
                if self._restore_handler is not None:
                    self._restore_handler()
        self._run(operation, callback=restored)

    def _prepare_local(self, panel):
        if self._busy:
            return
        if not self._restore_allowed():
            self._message = _("Save or discard unsaved edits before restoring a cloud backup.")
            self._update()
            return
        path, _filter = QFileDialog.getOpenFileName(panel, _("Restore local recovery copy"), "", _("Personal backup files (*.wlbackup)"))
        if not path:
            return
        def ready(result):
            if not result.ok or not isValid(panel):
                return
            if not self._restore_allowed():
                return
            dialog = BackupTransferDialog(result.value, restore=True, parent=panel, local_path=path)
            self._confirming = True
            try:
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    passphrase = dialog.passphrase.text()
                    self._restore(panel, lambda: self.service.restore_local(path, expected_local_digest=result.value.local_digest,
                        expected_archive_digest=result.value.archive_digest, passphrase=passphrase))
            finally:
                self._confirming = False
                dialog.deleteLater()
        self._run(lambda: self.service.preview_local(path), callback=ready)

    def _owner_busy(self):
        if self._owner is None:
            return False
        settings = getattr(self._owner, "_settings_page", None)
        dialog = getattr(self._owner, "_settings_dialog", None)
        if dialog is not None:
            settings = dialog.page
        return any(bool(getattr(part, "is_busy", False)) for part in (
            self._owner.entry_panel, getattr(self._owner, "reports_page", None), settings))

    def _restore_allowed(self):
        return not self._owner_busy() and (self._owner is None or not self._owner.has_unsaved_changes)

    def _tick(self):
        if (self._busy or self._confirming or self._configuration is None
                or monotonic() < max(self._retry_at, self._startup_ready_at)):
            return
        if self._owner_busy():
            return
        if self._state.get("last_error") in {"cloud_conflict", "cloud_local_changed", "cloud_configuration_invalid"}:
            return
        last = self._state.get("last_success")
        previous = datetime.fromisoformat(last) if last else None
        if backup_due(self._configuration, previous, datetime.now(get_localzone())):
            self._run(self.service.upload, success=_("Cloud backup uploaded."), automatic=True)
