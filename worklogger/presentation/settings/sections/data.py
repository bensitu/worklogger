"""Data settings controls."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QPushButton,
    QLineEdit,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.settings.sections.actions import SectionActions
from worklogger.presentation.settings.sections.common import (
    _action_card,
    _add_action_buttons,
    _secondary_label,
    _SettingsScrollPage,
)
from worklogger.presentation.widgets.icons import set_button_icon


class DataSection(_SettingsScrollPage):
    control_names = (
        "data_directory_input",
        "open_data_directory_button",
        "backup_button",
        "backup_status_label",
        "clear_calendar_events_button",
        "data_status_label",
        "export_csv_button",
        "export_ics_button",
        "import_csv_button",
        "import_ics_button",
        "restore_button",
    )

    def __init__(self, actions: SectionActions):
        super().__init__()
        page = self
        location = _action_card(_("Data location"),
            _("Your local database is stored here. Open this folder to locate it; use Backup Data to create a safe copy."))
        self.data_directory_input = QLineEdit()
        self.data_directory_input.setObjectName("data_directory_line_edit")
        self.data_directory_input.setReadOnly(True)
        self.data_directory_input.setAccessibleName(_("Data directory"))
        location.content_layout.addWidget(self.data_directory_input)
        self.open_data_directory_button = QPushButton(_("Open data directory"))
        self.open_data_directory_button.setProperty("variant", "outline")
        self.open_data_directory_button.setEnabled(False)
        self.open_data_directory_button.clicked.connect(actions.open_data_directory_requested)
        set_button_icon(self.open_data_directory_button, "folder-open")
        location.content_layout.addWidget(self.open_data_directory_button)
        page.layout().addWidget(location)
        csv_card = _action_card(
            _("CSV Data Management"),
            _(
                "Import or export worklog records as CSV files for backup, migration, or spreadsheet analysis."
            ),
        )
        self.export_csv_button = QPushButton(_("Export CSV"))
        self.export_csv_button.setObjectName("export_csv_button")
        self.export_csv_button.setProperty("variant", "outline")
        self.export_csv_button.clicked.connect(actions.export_csv_requested)
        self.import_csv_button = QPushButton(_("Import CSV"))
        self.import_csv_button.setObjectName("import_csv_button")
        self.import_csv_button.setProperty("variant", "outline")
        self.import_csv_button.clicked.connect(actions.import_csv_requested)
        set_button_icon(self.export_csv_button, "file-output")
        set_button_icon(self.import_csv_button, "file-input")
        _add_action_buttons(
            csv_card, self.export_csv_button, self.import_csv_button, columns=2
        )
        page.layout().addWidget(csv_card)

        backup_card = _action_card(
            _("Database Backup"),
            _(
                "Back up your database regularly to protect your local work logs, reports, settings, and account data."
            ),
        )
        self.backup_button = QPushButton(_("Backup Data"))
        self.backup_button.setObjectName("backup_button")
        self.backup_button.setProperty("variant", "outline")
        self.backup_button.clicked.connect(actions.backup_requested)
        self.restore_button = QPushButton(_("Restore Data"))
        self.restore_button.setObjectName("restore_button")
        self.restore_button.setProperty("variant", "outline")
        self.restore_button.clicked.connect(actions.restore_requested)
        set_button_icon(self.backup_button, "database")
        set_button_icon(self.restore_button, "rotate-ccw")
        _add_action_buttons(
            backup_card, self.backup_button, self.restore_button, columns=2
        )
        self.backup_status_label = _secondary_label(
            _("No backup recorded. Back up your data.")
        )
        self.backup_status_label.setObjectName("backup_status_label")
        backup_card.content_layout.addWidget(self.backup_status_label)
        self.data_status_label = _secondary_label("")
        self.data_status_label.setObjectName("data_operation_status_label")
        self.data_status_label.hide()
        backup_card.content_layout.addWidget(self.data_status_label)
        page.layout().addWidget(backup_card)

        calendar_card = _action_card(
            _("Calendar Data"),
            _(
                "Import your .ics file to let AI read your meetings when generating reports."
            ),
        )
        self.import_ics_button = QPushButton(_("Import Calendar (.ics)"))
        self.import_ics_button.setObjectName("import_ics_button")
        self.import_ics_button.setProperty("variant", "outline")
        self.import_ics_button.clicked.connect(actions.import_ics_requested)
        self.export_ics_button = QPushButton(_("Export .ics"))
        self.export_ics_button.setObjectName("export_ics_button")
        self.export_ics_button.setProperty("variant", "outline")
        self.export_ics_button.clicked.connect(actions.export_ics_requested)
        self.clear_calendar_events_button = QPushButton(_("Clear Calendar Events"))
        self.clear_calendar_events_button.setObjectName("clear_calendar_events_button")
        self.clear_calendar_events_button.setProperty("variant", "danger")
        self.clear_calendar_events_button.setEnabled(False)
        self.clear_calendar_events_button.setToolTip(
            _("Clearing calendar events is not supported yet.")
        )
        for button, icon in (
            (self.import_ics_button, "file-input"),
            (self.export_ics_button, "file-output"),
            (self.clear_calendar_events_button, "trash"),
        ):
            set_button_icon(button, icon)
        _add_action_buttons(
            calendar_card,
            self.import_ics_button,
            self.export_ics_button,
            self.clear_calendar_events_button,
        )
        page.layout().addWidget(calendar_card)
        page.layout().addStretch(1)
