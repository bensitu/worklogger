"""Report editing controls independent of persistence and background workflows."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QToolButton

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.card import CardFrame
from worklogger.presentation.widgets.export_menu_button import ExportMenuButton
from worklogger.presentation.widgets.icons import IconLabel, set_button_icon
from worklogger.presentation.widgets.processing_progress import ProcessingProgress


class ReportEditorPanel(CardFrame):
    control_names = (
        "period_title_label",
        "previous_period_button",
        "next_period_button",
        "templates_button",
        "generate_button",
        "editor",
        "report_state_label",
        "ai_hint_line_edit",
        "ai_assist_button",
        "versions_button",
        "processing_progress",
        "copy_button",
        "save_button",
        "export_current_button",
    )

    def __init__(self, parent=None, *, ai_ready=True, timesheet_available=False):
        super().__init__(parent, object_name="report_editor_frame")
        period_row = QHBoxLayout()
        self.period_title_label = QLabel("")
        self.period_title_label.setObjectName("report_period_label")
        self.period_title_label.setProperty("role", "title")
        self.previous_period_button = QPushButton("<")
        self.previous_period_button.setObjectName("previous_report_period_button")
        self.previous_period_button.setProperty("variant", "outline")
        self.previous_period_button.setToolTip(_("Previous period"))
        self.previous_period_button.setAccessibleName(_("Previous period"))
        set_button_icon(self.previous_period_button, "chevron-left")
        self.previous_period_button.setText("")
        self.next_period_button = QPushButton(">")
        self.next_period_button.setObjectName("next_report_period_button")
        self.next_period_button.setProperty("variant", "outline")
        self.next_period_button.setToolTip(_("Next period"))
        self.next_period_button.setAccessibleName(_("Next period"))
        set_button_icon(self.next_period_button, "chevron-right")
        self.next_period_button.setText("")
        period_row.addWidget(IconLabel("calendar-days"))
        self.period_title_label.setWordWrap(True)
        period_row.addWidget(self.period_title_label, 1)
        self.previous_period_button.setFixedWidth(34)
        self.next_period_button.setFixedWidth(34)
        period_row.addWidget(self.previous_period_button)
        period_row.addWidget(self.next_period_button)
        self.content_layout.addLayout(period_row)
        divider = QFrame()
        divider.setObjectName("report_period_separator_frame")
        divider.setFixedHeight(1)
        self.content_layout.addWidget(divider)

        report_row = QHBoxLayout()
        report_title = QLabel(_("Report"))
        report_title.setObjectName("report_title_label")
        self.templates_button = QPushButton(_("Templates"))
        self.templates_button.setObjectName("templates_button")
        self.templates_button.setProperty("variant", "outline")
        set_button_icon(self.templates_button, "file-text")
        report_row.addWidget(report_title, 1)
        self.generate_button = QPushButton(_("Generate from records"))
        self.generate_button.setObjectName("generate_report_button")
        set_button_icon(self.generate_button, "file-plus-2")
        report_row.addWidget(self.generate_button)
        report_row.addWidget(self.templates_button)
        self.content_layout.addLayout(report_row)

        self.editor = QTextEdit()
        self.editor.setObjectName("report_text_edit")
        self.editor.setAcceptRichText(False)
        self.report_state_label = QLabel()
        self.report_state_label.setObjectName("report_state_label")
        self.report_state_label.setProperty("role", "secondary")
        self.report_state_label.setWordWrap(True)
        self.content_layout.addWidget(self.report_state_label)
        self.content_layout.addWidget(self.editor, 1)

        self.ai_hint_line_edit = QLineEdit()
        self.ai_hint_line_edit.setObjectName("ai_hint_line_edit")
        self.ai_hint_line_edit.setPlaceholderText(_("AI Assist Hint / extra instructions (optional)"))
        self.content_layout.addWidget(self.ai_hint_line_edit)

        ai_row = QHBoxLayout()
        self.ai_assist_button = QPushButton(_("Polish text"))
        self.ai_assist_button.setObjectName("report_ai_assist_button")
        self.ai_assist_button.setProperty("variant", "outline")
        set_button_icon(self.ai_assist_button, "sparkles")
        if not ai_ready:
            self.ai_assist_button.setEnabled(False)
            self.ai_assist_button.setToolTip(_("AI Assist is not configured."))
            self.ai_hint_line_edit.setEnabled(False)
        ai_row.addWidget(self.ai_assist_button)
        ai_row.addStretch(1)
        self.versions_button = QPushButton(_("Report versions"))
        set_button_icon(self.versions_button, "history")
        ai_row.addWidget(self.versions_button)
        self.content_layout.addLayout(ai_row)
        self.processing_progress = ProcessingProgress()
        self.content_layout.addWidget(self.processing_progress)

        bottom = QHBoxLayout()
        self.copy_button = QToolButton()
        self.copy_button.setProperty("variant", "outline")
        self.copy_button.setToolTip(_("Copy Markdown"))
        self.copy_button.setAccessibleName(_("Copy Markdown"))
        self.copy_button.setFixedSize(40, 40)
        self.copy_button.setObjectName("copy_report_button")
        set_button_icon(self.copy_button, "copy", format_label="MD")
        self.save_button = QPushButton(_("Save Report"))
        self.save_button.setObjectName("save_report_button")
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        bottom.addWidget(self.copy_button)
        self.export_current_button = ExportMenuButton(_("Export report"),
            (("current", _("Current visible report (Markdown)")), ("day", _("Saved daily report (Markdown)")),
             ("month", _("Saved daily reports for this month (Markdown)"))))
        self.export_current_button.setObjectName("export_current_report_button")
        self.export_current_button.setProperty("variant", "outline")
        self.export_current_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        set_button_icon(self.export_current_button, "file-output")
        self.export_current_button.setMinimumWidth(self.export_current_button.fontMetrics().horizontalAdvance(self.export_current_button.text()) + 56)
        if timesheet_available:
            menu = self.export_current_button.menu().addMenu(_("Timesheet"))
            for key, caption in (("timesheet_day_xlsx", _("Selected day (Excel)")), ("timesheet_month_xlsx", _("Selected month (Excel)")),
                                 ("timesheet_day_pdf", _("Selected day (PDF)")), ("timesheet_month_pdf", _("Selected month (PDF)"))):
                action = menu.addAction(caption)
                action.setData(key)
                action.triggered.connect(lambda _checked=False, key=key: self.export_current_button.export_requested.emit(key))
        bottom.addWidget(self.export_current_button)
        bottom.addStretch(1)
        bottom.addWidget(self.save_button)
        self.content_layout.addLayout(bottom)
