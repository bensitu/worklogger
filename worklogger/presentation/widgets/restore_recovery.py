"""Explicit startup choice after interrupted database replacement."""

from PySide6.QtWidgets import QMessageBox

from worklogger.infrastructure.i18n import _


def choose_restore_recovery(choices):
    dialog = QMessageBox()
    dialog.setWindowTitle(_("Recover interrupted restore"))
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setText(_("A database restore was interrupted. Choose which database to use. Both copies will be retained. Cancel leaves all files unchanged."))
    rollback = dialog.addButton(_("Roll back to previous database"), QMessageBox.ButtonRole.AcceptRole)
    keep = dialog.addButton(_("Keep restored database"), QMessageBox.ButtonRole.ActionRole)
    cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
    cancel.setText(_("Cancel"))
    rollback.setEnabled(choices.rollback_available)
    keep.setEnabled(choices.restored_available)
    dialog.setDefaultButton(cancel)
    dialog.setEscapeButton(cancel)
    dialog.exec()
    return "rollback" if dialog.clickedButton() is rollback else "keep" if dialog.clickedButton() is keep else None
