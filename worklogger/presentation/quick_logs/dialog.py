"""Quick Log management dialog."""

from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from worklogger.domain.quicklog.models import QuickLog
from worklogger.domain.shared.errors import AppError, ValidationError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.viewmodels import QuickLogEditorState, QuickLogEditorViewModel


class QuickLogDialog(QDialog):
    def __init__(
        self,
        view_model: QuickLogEditorViewModel,
        day: date,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._view_model = view_model
        self._day = day
        self._state: QuickLogEditorState | None = None
        self._last_error: AppError | None = None
        self.setObjectName("quick_log_dialog")
        self.setWindowTitle(_("Quick Log"))
        self._build_ui()

    @property
    def last_error(self) -> AppError | None:
        return self._last_error

    def refresh(self) -> bool:
        result = self._view_model.load(self._day)
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return False
        self.set_state(result.value)
        self.status_label.setText(_("Ready"))
        return True

    def set_state(self, state: QuickLogEditorState) -> None:
        self._state = state
        self.date_label.setText(state.day.isoformat())
        self.list_widget.clear()
        for quick_log in state.quick_logs:
            item = QListWidgetItem(_quick_log_text(quick_log))
            item.setData(256, quick_log)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)
        else:
            self._clear_inputs()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self.date_label = QLabel("")
        self.date_label.setObjectName("quick_log_date_label")
        root.addWidget(self.date_label)

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("quick_log_list_widget")
        root.addWidget(self.list_widget, 1)

        form = QFormLayout()
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("09:00")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("09:30")
        self.description_input = QLineEdit()
        form.addRow(_("Start"), self.start_input)
        form.addRow(_("End"), self.end_input)
        form.addRow(_("Description"), self.description_input)
        root.addLayout(form)

        tools = QHBoxLayout()
        self.add_button = QPushButton(_("Add"))
        self.update_button = QPushButton(_("Update"))
        self.delete_button = QPushButton(_("Delete"))
        self.refresh_button = QPushButton(_("Refresh"))
        tools.addWidget(self.add_button)
        tools.addWidget(self.update_button)
        tools.addWidget(self.delete_button)
        tools.addWidget(self.refresh_button)
        tools.addStretch(1)
        root.addLayout(tools)

        bottom = QHBoxLayout()
        self.status_label = QLabel("")
        self.close_button = QPushButton(_("Close"))
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.close_button)
        root.addLayout(bottom)

        self.list_widget.currentItemChanged.connect(lambda _current, _previous: self._load_selected())
        self.add_button.clicked.connect(self._add)
        self.update_button.clicked.connect(self._update)
        self.delete_button.clicked.connect(self._delete)
        self.refresh_button.clicked.connect(self.refresh)
        self.close_button.clicked.connect(self.accept)

    def selected_quick_log(self) -> QuickLog | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        value = item.data(256)
        return value if isinstance(value, QuickLog) else None

    def _load_selected(self) -> None:
        quick_log = self.selected_quick_log()
        if quick_log is None:
            self._clear_inputs()
            return
        self.start_input.setText(quick_log.start_time)
        self.end_input.setText(quick_log.end_time)
        self.description_input.setText(quick_log.description)

    def _add(self) -> None:
        result = self._view_model.add(
            self._day,
            description=self.description_input.text(),
            start_time=self.start_input.text(),
            end_time=self.end_input.text(),
        )
        self._handle_mutation(result, _("Quick Log added."))

    def _update(self) -> None:
        quick_log = self.selected_quick_log()
        if quick_log is None or quick_log.id is None:
            self._set_error(ValidationError("quick_log_not_selected", "quick_log_not_selected"))
            return
        result = self._view_model.update(
            quick_log.id,
            self._day,
            description=self.description_input.text(),
            start_time=self.start_input.text(),
            end_time=self.end_input.text(),
        )
        self._handle_mutation(result, _("Quick Log updated."))

    def _delete(self) -> None:
        quick_log = self.selected_quick_log()
        if quick_log is None or quick_log.id is None:
            self._set_error(ValidationError("quick_log_not_selected", "quick_log_not_selected"))
            return
        result = self._view_model.delete(quick_log.id, self._day)
        self._handle_mutation(result, _("Quick Log deleted."))

    def _handle_mutation(
        self,
        result,
        message: str,
    ) -> None:
        if not result.ok or result.value is None:
            self._set_error(result.error)
            return
        self.set_state(result.value)
        self.status_label.setText(message)

    def _clear_inputs(self) -> None:
        self.start_input.clear()
        self.end_input.clear()
        self.description_input.clear()

    def _set_error(self, error: AppError | None) -> None:
        self._last_error = error
        self.status_label.setText(error.message if error is not None else _("Unknown error"))


def _quick_log_text(quick_log: QuickLog) -> str:
    time_text = _time_range(quick_log.start_time, quick_log.end_time)
    prefix = f"{time_text}  " if time_text else ""
    return f"{prefix}{quick_log.description}"


def _time_range(start_time: str | None, end_time: str | None) -> str:
    start = str(start_time or "").strip()
    end = str(end_time or "").strip()
    if start and end:
        return f"{start}-{end}"
    return start or end
