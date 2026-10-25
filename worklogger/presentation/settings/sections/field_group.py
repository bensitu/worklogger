"""Responsive labeled fields shared by settings sections."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QLayout, QSizePolicy, QWidget


class SettingsFieldGroup(QWidget):
    def __init__(self, rows: list[tuple[str, QLabel, QWidget]]):
        super().__init__()
        self.setObjectName("settings_field_group_widget")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(8)
        self._grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._fields = {}
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
        return QSize(max(widget.minimumSizeHint().width() for pair in self._fields.values() for widget in pair),
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
        minimum = max(160, self.minimumSizeHint().width())
        columns = max(1, min(len(visible), (self.width() + 12) // (minimum + 12)))
        signature = visible, columns
        if signature == self._signature:
            return
        self._signature = signature
        while self._grid.count():
            self._grid.takeAt(0)
        for column in range(self._grid.columnCount()):
            self._grid.setColumnStretch(column, 0)
        for index, name in enumerate(visible):
            label, field = self._fields[name]
            self._grid.addWidget(label, index // columns * 2, index % columns)
            alignment = Qt.AlignmentFlag.AlignTop
            if field.maximumWidth() < self.maximumWidth():
                alignment |= Qt.AlignmentFlag.AlignLeft
            self._grid.addWidget(field, index // columns * 2 + 1, index % columns, alignment)
            self._grid.setColumnStretch(index % columns, 1)
        self.updateGeometry()
