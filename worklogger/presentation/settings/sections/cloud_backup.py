"""Personal cloud backup configuration and transfer controls."""

from dataclasses import fields
from uuid import uuid4

from PySide6.QtCore import QLocale, QTime, Signal, Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPushButton, QSpinBox, QTimeEdit, QWidget

from worklogger.domain.cloud_backup import BackupConfiguration, BackupCredentials
from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.settings.sections.common import _card_with_form, _add_action_buttons, _secondary_label
from worklogger.presentation.widgets.icons import set_button_icon


def _number(minimum, maximum):
    field = QSpinBox()
    field.setRange(minimum, maximum)
    return field


class CloudBackupPanel(QWidget):
    save_requested = Signal(object, object)
    test_requested = Signal()
    upload_requested = Signal()
    restore_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QVBoxLayout
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        card = _card_with_form(_("Personal cloud backup"))
        root.addWidget(card)
        self.provider = QComboBox()
        self.provider.addItem("WebDAV", "webdav")
        self.provider.addItem(_("S3-compatible storage"), "s3")
        self.endpoint, self.username, self.password = QLineEdit(), QLineEdit(), QLineEdit()
        self.prefix, self.bucket, self.region = QLineEdit(), QLineEdit(), QLineEdit()
        self.passphrase, self.session_token = QLineEdit(), QLineEdit()
        for secret in (self.password, self.passphrase, self.session_token):
            secret.setEchoMode(QLineEdit.EchoMode.Password)
            secret.setMaxLength(4096)
        for text in (self.endpoint, self.username, self.prefix, self.bucket, self.region):
            text.setMaxLength(1024)
        self.encrypted = QCheckBox(_("Client-side encryption"))
        self.keep_count, self.keep_days = _number(1, 200), _number(1, 3650)
        self.schedule = QComboBox()
        for caption, key in ((_("Off"), "off"), (_("Every N hours"), "interval"), (_("Every day"), "daily"),
                             (_("Every week"), "weekly"), (_("Every month"), "monthly")):
            self.schedule.addItem(caption, key)
        self.interval_hours, self.month_day = _number(1, 8760), _number(1, 31)
        self.time = QTimeEdit()
        self.time.setDisplayFormat("HH:mm")
        self.weekday = QComboBox()
        locale = QLocale(get_language())
        for weekday in range(1, 8):
            self.weekday.addItem(locale.dayName(weekday), weekday - 1)
        self._rows = {}
        labels = (("provider", _("Storage provider")), ("endpoint", _("HTTPS endpoint")),
                  ("prefix", _("Backup directory / prefix")), ("username", _("Username / access key ID")),
                  ("password", _("Password / secret access key")), ("bucket", _("S3 bucket")),
                  ("region", _("S3 region")), ("session_token", _("S3 session token")),
                  ("encrypted", ""), ("passphrase", _("Backup passphrase")),
                  ("keep_count", _("Maximum retained backups")), ("keep_days", _("Retention days")),
                  ("schedule", _("Automatic backup")), ("interval_hours", _("Interval (hours)")),
                  ("time", _("Local time")), ("weekday", _("Day of week")), ("month_day", _("Day of month")))
        for name, caption in labels:
            field = getattr(self, name)
            field.setAccessibleName(caption or _("Client-side encryption"))
            card.form_layout.addRow(caption, field)
            self._rows[name] = (card.form_layout.labelForField(field), field)
        self.save_button, self.test_button = QPushButton(_("Save")), QPushButton(_("Test connection"))
        self.upload_button, self.restore_button = QPushButton(_("Upload backup")), QPushButton(_("Download and restore"))
        for button, icon in ((self.save_button, "save"), (self.test_button, "link"),
                             (self.upload_button, "upload"), (self.restore_button, "download")):
            button.setProperty("variant", "outline")
            set_button_icon(button, icon)
        _add_action_buttons(card, self.save_button, self.test_button, self.upload_button, self.restore_button, columns=2)
        self.status_label = _secondary_label("")
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        card.content_layout.addWidget(self.status_label)
        self.save_button.clicked.connect(self._save)
        self.test_button.clicked.connect(self.test_requested.emit)
        self.upload_button.clicked.connect(self.upload_requested.emit)
        self.restore_button.clicked.connect(self.restore_requested.emit)
        self.provider.currentIndexChanged.connect(self._sync_rows)
        self.schedule.currentIndexChanged.connect(self._sync_rows)
        self.encrypted.toggled.connect(self._sync_rows)
        self._saved_configuration = None
        self._credentials = BackupCredentials()
        self.set_configuration(BackupConfiguration(prefix="worklogger/" + uuid4().hex), self._credentials)
        self._saved_configuration = None
        self.setEnabled(False)

    def _sync_rows(self, *_args):
        provider, schedule = self.provider.currentData(), self.schedule.currentData()
        visible = {"bucket": provider == "s3", "region": provider == "s3", "session_token": provider == "s3",
                   "passphrase": self.encrypted.isChecked(), "interval_hours": schedule == "interval",
                   "time": schedule in {"daily", "weekly", "monthly"}, "weekday": schedule == "weekly",
                   "month_day": schedule == "monthly"}
        for name, shown in visible.items():
            label, field = self._rows[name]
            field.setVisible(shown)
            if label is not None:
                label.setVisible(shown)

    def set_configuration(self, configuration, credentials):
        self._saved_configuration, self._credentials = configuration, credentials
        for field in fields(configuration):
            control, value = getattr(self, field.name), getattr(configuration, field.name)
            if isinstance(control, QComboBox):
                control.setCurrentIndex(control.findData(value))
            elif isinstance(control, QCheckBox):
                control.setChecked(value)
            elif isinstance(control, QSpinBox):
                control.setValue(value)
            elif isinstance(control, QTimeEdit):
                control.setTime(QTime.fromString(value, "HH:mm"))
            else:
                control.setText(value)
        self.username.setText(credentials.username)
        for name in ("password", "passphrase", "session_token"):
            control = getattr(self, name)
            control.clear()
            control.setPlaceholderText(_("Stored securely") if getattr(credentials, name) else "")
        self._sync_rows()

    def _save(self):
        from PySide6.QtWidgets import QMessageBox
        configuration = BackupConfiguration(provider=self.provider.currentData(), endpoint=self.endpoint.text().strip(),
            prefix=self.prefix.text().strip().strip("/"), bucket=self.bucket.text().strip(), region=self.region.text().strip(),
            encrypted=self.encrypted.isChecked(), keep_count=self.keep_count.value(), keep_days=self.keep_days.value(),
            schedule=self.schedule.currentData(), interval_hours=self.interval_hours.value(), time=self.time.time().toString("HH:mm"),
            weekday=self.weekday.currentData(), month_day=self.month_day.value())
        if not configuration.encrypted and (self._saved_configuration is None or self._saved_configuration.encrypted):
            if QMessageBox.warning(self, _("Unencrypted backup"),
                _("Anyone with access to these cloud files can read your data. Continue without encryption?"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
        credentials = BackupCredentials(self.username.text().strip(), self.password.text() or self._credentials.password,
            self.session_token.text() or self._credentials.session_token, self.passphrase.text() or self._credentials.passphrase)
        self.save_requested.emit(configuration, credentials)

    def set_busy(self, busy, *, configured):
        self.setEnabled(not busy)
        for button in (self.upload_button, self.restore_button, self.test_button):
            button.setEnabled(not busy and configured)
