"""Consistent information dialogs with readable text and comfortable spacing."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QSizePolicy, QSpacerItem

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.assets import apply_window_icon


def information_dialog(parent, title: str, message: str, *, detail: str = "") -> QMessageBox:
    dialog = QMessageBox(QMessageBox.Icon.Information, title, message, QMessageBox.StandardButton.Ok, parent)
    dialog.setObjectName("information_feedback_dialog")
    apply_window_icon(dialog)
    dialog.setTextFormat(Qt.TextFormat.PlainText)
    if detail:
        dialog.setInformativeText(detail)
    dialog.button(QMessageBox.StandardButton.Ok).setText(_("Close"))
    layout = dialog.layout()
    layout.setContentsMargins(24, 20, 24, 20)
    layout.setHorizontalSpacing(16)
    layout.setVerticalSpacing(16)
    layout.addItem(QSpacerItem(320, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum),
                   layout.rowCount(), 0, 1, layout.columnCount())
    return dialog


def show_information(parent, title: str, message: str, *, detail: str = "") -> None:
    dialog = information_dialog(parent, title, message, detail=detail)
    try:
        dialog.exec()
    finally:
        dialog.deleteLater()
