"""Shared information dialogs and record-editing confirmations."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QSizePolicy, QSpacerItem

from worklogger.infrastructure.i18n import _
from worklogger.presentation.widgets.assets import apply_window_icon


def confirm_discard_record_changes(parent) -> bool:
    return QMessageBox.question(parent, _("Discard changes?"),
        _("You have unsaved work log changes. Discard them?"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes


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


def show_warning(parent, title: str, message: str) -> None:
    dialog = parent.findChild(QMessageBox, "warning_feedback_dialog")
    if dialog is None:
        dialog = QMessageBox(QMessageBox.Icon.Warning, title, message, QMessageBox.StandardButton.Ok, parent)
        dialog.setObjectName("warning_feedback_dialog")
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
    else:
        dialog.setWindowTitle(title)
        dialog.setText(message)
    dialog.show()
