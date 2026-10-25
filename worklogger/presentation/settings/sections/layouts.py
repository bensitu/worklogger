"""Responsive containers and shared spacing for settings pages."""

from collections.abc import Mapping, Sequence

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractButton, QGridLayout, QHBoxLayout, QLabel, QLayout,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

FIELD_SPACING = 8
COLUMN_SPACING = 12
SECTION_SPACING = 16
MIN_COLUMN_WIDTH = 160


class SettingsContainer(QWidget):
    def __init__(self, object_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setProperty("surface_role", "transparent")


class SettingsScrollPage(QScrollArea):
    def __init__(self):
        super().__init__()
        self.setObjectName("settings_scroll_widget")
        self.setWidgetResizable(True)
        self.content_widget = QWidget()
        self.content_widget.setObjectName("settings_scroll_content_widget")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(SECTION_SPACING)
        self.setWidget(self.content_widget)

    def layout(self) -> QVBoxLayout:
        return self.content_layout


def _grid(container):
    layout = QGridLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setHorizontalSpacing(COLUMN_SPACING)
    layout.setVerticalSpacing(FIELD_SPACING)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    return layout


def _clear_grid(layout):
    while layout.count():
        layout.takeAt(0)
    for column in range(layout.columnCount()):
        layout.setColumnStretch(column, 0)


def _columns(width, minimum, count):
    return max(1, min(count, (width + COLUMN_SPACING) // (max(MIN_COLUMN_WIDTH, minimum) + COLUMN_SPACING)))


class SettingsFieldGroup(SettingsContainer):
    def __init__(self, rows: Sequence[tuple[str, QLabel, QWidget]], *, weights: Mapping[str, int] | None = None):
        super().__init__("settings_field_group_widget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._grid = _grid(self)
        self._fields = {}
        self._weights = dict(weights or {})
        self._signature = None
        for name, label, field in rows:
            label.setParent(self)
            field.setParent(self)
            label.setVisible(True)
            field.setVisible(True)
            label.setWordWrap(True)
            label.setBuddy(field)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._fields[name] = label, field
        self.reflow()

    def minimumSizeHint(self):
        return QSize(max((widget.minimumSizeHint().width() for pair in self._fields.values() for widget in pair), default=0),
                     self._grid.minimumSize().height())

    def set_field_visible(self, name, visible):
        for widget in self._fields[name]:
            widget.setVisible(visible)

    def sync_visibility(self):
        self.setVisible(any(not field.isHidden() for _label, field in self._fields.values()))
        self.reflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def reflow(self):
        visible = tuple(name for name, (_label, field) in self._fields.items() if not field.isHidden())
        columns = _columns(self.width(), self.minimumSizeHint().width(), len(visible))
        signature = visible, columns
        if signature == self._signature:
            return
        self._signature = signature
        _clear_grid(self._grid)
        for index, name in enumerate(visible):
            label, field = self._fields[name]
            self._grid.addWidget(label, index // columns * 2, index % columns)
            alignment = Qt.AlignmentFlag.AlignTop
            if field.maximumWidth() < self.maximumWidth():
                alignment |= Qt.AlignmentFlag.AlignLeft
            self._grid.addWidget(field, index // columns * 2 + 1, index % columns, alignment)
            column = index % columns
            self._grid.setColumnStretch(column, max(self._grid.columnStretch(column), self._weights.get(name, 1)))
        self.updateGeometry()


class SettingsActionGroup(SettingsContainer):
    def __init__(self, buttons: Sequence[QAbstractButton], *, columns: int = 2):
        super().__init__("settings_action_group_widget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._grid = _grid(self)
        self._buttons = tuple(buttons)
        self._maximum_columns = max(1, columns)
        self._signature = None
        for button in self._buttons:
            button.setParent(self)
            button.setVisible(True)
        self.reflow()

    def minimumSizeHint(self):
        return QSize(max((button.minimumSizeHint().width() for button in self._buttons), default=0),
                     self._grid.minimumSize().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def reflow(self):
        columns = min(self._maximum_columns, _columns(self.width(), self.minimumSizeHint().width(), len(self._buttons)))
        if columns == self._signature:
            return
        self._signature = columns
        _clear_grid(self._grid)
        for index, button in enumerate(self._buttons):
            self._grid.addWidget(button, index // columns, index % columns)
            self._grid.setColumnStretch(index % columns, 1)
        self.updateGeometry()


class HalfWidthFieldRow(SettingsContainer):
    def __init__(self, field: QWidget, accessory: QWidget | None):
        super().__init__("settings_half_width_field_row_widget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._field, self._accessory = field, accessory
        self._minimum_field_width = field.minimumWidth()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        layout.addWidget(field)
        if accessory is not None:
            layout.addSpacing(COLUMN_SPACING)
            layout.addWidget(accessory)
        layout.addStretch(1)

    def minimumSizeHint(self):
        minimum = max(self._minimum_field_width, self._field.minimumSizeHint().width())
        accessory_width = self._accessory.width() + COLUMN_SPACING if self._accessory is not None else 0
        return QSize(minimum + accessory_width, self.layout().minimumSize().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        half = max(0, (self.width() - COLUMN_SPACING) // 2)
        minimum = max(MIN_COLUMN_WIDTH, self._minimum_field_width, self._field.minimumSizeHint().width())
        accessory_width = self._accessory.width() + COLUMN_SPACING if self._accessory is not None else 0
        width = half if half >= minimum else max(0, self.width() - accessory_width)
        if self._field.minimumWidth() != width or self._field.maximumWidth() != width:
            self._field.setFixedWidth(width)
