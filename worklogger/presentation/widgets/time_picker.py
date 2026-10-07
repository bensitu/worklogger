"""Time selection for independently recorded periods."""

from PySide6.QtCore import QTime, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTimeEdit, QVBoxLayout, QWidget
from worklogger.domain.worklog.rules import parse_time
from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.assets import apply_window_icon


class TimePickerDialog(QDialog):
    def __init__(self, title: str, initial_time: str, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("manual_time_picker_dialog")
        self.setWindowTitle(title)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        apply_window_icon(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        self.time_input = QTimeEdit()
        self.time_input.setObjectName("manual_time_picker_widget")
        self.time_input.setDisplayFormat("HH:mm")
        self.time_input.setKeyboardTracking(False)
        self.time_input.setTimeRange(QTime(0, 0), QTime(23, 59))
        parsed = parse_time(initial_time)
        self.time_input.setTime(QTime.fromString(parsed, "HH:mm") if parsed else QTime.currentTime())
        root.addWidget(self.time_input)
        row = QHBoxLayout()
        row.addStretch()
        self.close_button = QPushButton(_("Close"))
        self.close_button.setObjectName("manual_time_picker_close_button")
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        self.select_button = QPushButton(_("Select"))
        self.select_button.setObjectName("manual_time_picker_select_button")
        self.select_button.setProperty("variant", "primary")
        self.select_button.setDefault(True)
        self.select_button.clicked.connect(self.accept)
        row.addWidget(self.select_button)
        root.addLayout(row)
        self.setMinimumWidth(260)
