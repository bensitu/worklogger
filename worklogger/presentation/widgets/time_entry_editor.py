"""Time-record editor controls without persistence or action dependencies."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.classification_picker import ClassificationButton
from worklogger.presentation.widgets.icons import set_button_icon, ui_icon
from worklogger.presentation.widgets.processing_progress import ProcessingProgress


class TimeEntryEditorControls:
    control_names = (
        "time_tabs",
        "selected_record_label",
        "start_input",
        "end_input",
        "clock_in_button",
        "clock_out_button",
        "break_button",
        "discard_timer_button",
        "auto_status_label",
        "classification_button",
        "content_heading",
        "polish_button",
        "content_heading_stack",
        "processing_progress",
        "content_input",
        "hours_label",
        "actions_widget",
        "save_button",
        "clear_button",
        "undo_button",
        "history_label",
    )

    def __init__(self, parent: QWidget):
        root = QVBoxLayout(parent)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.time_tabs = QTabWidget()
        self.time_tabs.setObjectName("worklog_mode_tab_widget")
        self.time_tabs.setDocumentMode(True)
        self.time_tabs.tabBar().setObjectName("worklog_mode_selector_widget")
        self.time_tabs.tabBar().setProperty("tab_style", "segmented")
        self.time_tabs.tabBar().setProperty("density", "compact")
        self.time_tabs.tabBar().setProperty("selection_style", "subtle")
        self.time_tabs.tabBar().setExpanding(True)
        self.time_tabs.tabBar().setDrawBase(False)
        root.addWidget(self.time_tabs)
        self.selected_record_label = QLabel()
        self.selected_record_label.setProperty("role", "secondary")
        self.selected_record_label.setWordWrap(True)
        self.selected_record_label.hide()
        root.addWidget(self.selected_record_label)
        manual = QWidget()
        manual.setObjectName("worklog_manual_tab_widget")
        manual_layout = QHBoxLayout(manual)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(8)
        self.start_input, self.start_time_action = self._time_input("start_time_line_edit", _("Start"))
        self.end_input, self.end_time_action = self._time_input("end_time_line_edit", _("End"))
        for label, field in ((_("Start"), self.start_input), (_("End"), self.end_input)):
            column = QVBoxLayout()
            column.setSpacing(3)
            column.addWidget(QLabel(label))
            column.addWidget(field)
            manual_layout.addLayout(column, 1)
        self.time_tabs.addTab(manual, _("Manual Input"))
        auto = QWidget()
        auto.setObjectName("worklog_auto_tab_widget")
        auto_layout = QVBoxLayout(auto)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.clock_in_button = QPushButton(_("Start"))
        self.clock_out_button = QPushButton(_("End"))
        for button, name, icon in ((self.clock_in_button, "auto_clock_in_button", "clock"),
                                   (self.clock_out_button, "auto_clock_out_button", "check")):
            button.setObjectName(name)
            button.setProperty("variant", "primary")
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            set_button_icon(button, icon)
            buttons.addWidget(button)
        auto_layout.addLayout(buttons)
        self.break_button = QPushButton()
        self.break_button.setObjectName("auto_break_button")
        self.break_button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        break_row = QHBoxLayout()
        break_row.setSpacing(8)
        break_row.addWidget(self.break_button, 1)
        self.discard_timer_button = QPushButton(_("Discard timer"))
        self.discard_timer_button.setObjectName("discard_timer_button")
        self.discard_timer_button.setProperty("variant", "danger")
        set_button_icon(self.discard_timer_button, "trash")
        break_row.addWidget(self.discard_timer_button, 1)
        auto_layout.addLayout(break_row)
        self.auto_status_label = QLabel()
        self.auto_status_label.setObjectName("auto_status_label")
        self.auto_status_label.setWordWrap(True)
        auto_layout.addWidget(self.auto_status_label)
        self.time_tabs.addTab(auto, _("Auto Record"))

        classification_column = QVBoxLayout()
        classification_column.setSpacing(2)
        classification_caption = QLabel(_("Classification"))
        self.classification_button = ClassificationButton(parent)
        classification_caption.setBuddy(self.classification_button)
        classification_column.addWidget(classification_caption)
        classification_column.addWidget(self.classification_button)
        root.addLayout(classification_column)
        self.content_heading = QWidget()
        self.content_heading.setObjectName("time_entry_content_heading_widget")
        content_heading = QHBoxLayout(self.content_heading)
        content_heading.setContentsMargins(0, 0, 0, 0)
        content_heading.addWidget(QLabel(_("Content")), 1)
        self.polish_button = QToolButton()
        self.polish_button.setObjectName("polish_time_entry_button")
        self.polish_button.setToolTip(_("Polish text"))
        self.polish_button.setAccessibleName(_("Polish text"))
        self.polish_button.setProperty("variant", "outline")
        set_button_icon(self.polish_button, "sparkles")
        self.polish_button.setFixedSize(28, 28)
        content_heading.addWidget(self.polish_button)
        self.content_heading_stack = QStackedWidget()
        self.content_heading_stack.setObjectName("time_entry_content_heading_stack_widget")
        self.content_heading_stack.addWidget(self.content_heading)
        self.processing_progress = ProcessingProgress()
        self.processing_progress.bar.setFixedWidth(48)
        self.processing_progress.cancel_button.setFixedSize(28, 28)
        self.content_heading_stack.setFixedHeight(28)
        self.content_heading_stack.addWidget(self.processing_progress)
        self.content_heading_stack.setCurrentWidget(self.content_heading)
        content_column = QVBoxLayout()
        content_column.setContentsMargins(0, 0, 0, 0)
        content_column.setSpacing(3)
        content_column.addWidget(self.content_heading_stack)
        self.content_input = QTextEdit()
        self.content_input.setObjectName("time_entry_content_text_edit")
        self.content_input.setAcceptRichText(False)
        self.content_input.setFixedHeight(76)
        content_column.addWidget(self.content_input)
        root.addLayout(content_column)
        self.hours_label = QLabel()
        self.hours_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.hours_label.setObjectName("worklog_hours_label")
        root.addWidget(self.hours_label)
        self.actions_widget = QWidget()
        self.actions_widget.setObjectName("time_entry_actions_widget")
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        self.save_button = QPushButton(_("Save"))
        self.save_button.setObjectName("save_worklog_button")
        self.save_button.setProperty("variant", "primary")
        set_button_icon(self.save_button, "save")
        actions.addWidget(self.save_button, 1)
        self.clear_button = QToolButton()
        self.clear_button.setObjectName("clear_time_entry_button")
        self.clear_button.setProperty("variant", "outline")
        set_button_icon(self.clear_button, "eraser")
        self.clear_button.setToolTip(_("Clear input"))
        self.clear_button.setAccessibleName(_("Clear input"))
        actions.addWidget(self.clear_button)
        self.undo_button = QToolButton(self.actions_widget)
        self.undo_button.setObjectName("undo_record_change_button")
        self.undo_button.setProperty("variant", "outline")
        set_button_icon(self.undo_button, "rotate-ccw")
        self.undo_button.setToolTip(_("Undo latest record change"))
        self.undo_button.setAccessibleName(_("Undo latest record change"))
        actions.addWidget(self.undo_button)
        root.addWidget(self.actions_widget)
        self.history_label = QLabel()
        self.history_label.setObjectName("time_entry_history_label")
        self.history_label.setProperty("role", "secondary")
        self.history_label.setWordWrap(True)
        root.addWidget(self.history_label)

    @staticmethod
    def _time_input(name, title):
        field = QLineEdit()
        field.setObjectName(name)
        field.setAccessibleName(title)
        field.setMinimumWidth(0)
        field.setPlaceholderText("HH:mm")
        action = field.addAction(ui_icon("clock"), QLineEdit.ActionPosition.TrailingPosition)
        action.setText(title)
        action.setToolTip(title)
        return field, action
