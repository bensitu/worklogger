"""Shared settings dialogs, feedback, and path providers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from worklogger.app.use_cases.data_portability import WorkLogCsvImportPreview
from worklogger.app.use_cases.updates import UpdateCheckResult
from worklogger.domain.shared.errors import AppError
from worklogger.infrastructure.i18n import _
from worklogger.presentation.errors import display_error_message


def _set_status(dialog: QWidget, message: str, category: str | None = None) -> None:
    if hasattr(dialog, "set_operation_status"):
        if category is None:
            category = "data"
        dialog.set_operation_status(message, category)
    else:
        dialog.status_label.setText(message)


def _set_busy(surface: QWidget, job: str, busy: bool) -> None:
    if hasattr(surface, "set_busy"):
        surface.set_busy(job, busy)


def _error_message(error: AppError | None) -> str:
    return display_error_message(error)


def _update_message(result: UpdateCheckResult) -> str:
    if result.update_available and result.latest_version:
        return _("Update available: {version}").format(version=result.latest_version)
    return _("You are using the latest version.")


def _backup_destination(parent: QWidget | None) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_path(
        parent,
        _("Backup Data"),
        f"worklog_backup_{stamp}.db",
        _("SQLite Database (*.db)"),
    )


def _restore_source(parent: QWidget | None) -> Path | None:
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        _("Restore Data"),
        "",
        _("SQLite Database (*.db)"),
    )
    return Path(path) if path else None


def _csv_destination(parent: QWidget | None) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_path(
        parent,
        _("Export CSV"),
        f"worklog_{stamp}.csv",
        _("CSV (*.csv)"),
    )


def _csv_source(parent: QWidget | None) -> Path | None:
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        _("Import CSV"),
        "",
        _("CSV (*.csv)"),
    )
    return Path(path) if path else None


def _ics_destination(parent: QWidget | None) -> Path | None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _save_path(
        parent,
        _("Export .ics"),
        f"worklog_{stamp}.ics",
        _("iCalendar (*.ics)"),
    )


def _ics_source(parent: QWidget | None) -> Path | None:
    path, _selected_filter = QFileDialog.getOpenFileName(
        parent,
        _("Import .ics"),
        "",
        _("iCalendar (*.ics)"),
    )
    return Path(path) if path else None


def _save_path(
    parent: QWidget | None,
    title: str,
    default_name: str,
    file_filter: str,
) -> Path | None:
    path, _selected_filter = QFileDialog.getSaveFileName(
        parent,
        title,
        default_name,
        file_filter,
    )
    return Path(path) if path else None


def _confirm_csv_import(parent: QWidget, preview: WorkLogCsvImportPreview) -> bool:
    message = _(
        "Import {count} records, replace {existing} existing records, and skip {errors} invalid rows?"
    ).format(
        count=len(preview.rows),
        existing=preview.existing_count,
        errors=len(preview.errors),
    )
    return (
        QMessageBox.question(
            parent,
            _("Import CSV"),
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        == QMessageBox.StandardButton.Yes
    )


def _confirm_restore(parent: QWidget | None) -> bool:
    answer = QMessageBox.warning(
        parent,
        _("Restore Data"),
        _("Restore will replace the current database file. Continue?"),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def _choose_ics_import_mode(parent: QWidget | None) -> bool | None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(_("Import .ics"))
    box.setText(
        _(
            "Calendar data already exists.\n\n"
            "Replace clears previous calendar events before import.\n"
            "Append keeps existing events and adds imported events."
        )
    )
    replace_button = box.addButton(_("Replace"), QMessageBox.ButtonRole.DestructiveRole)
    append_button = box.addButton(_("Append"), QMessageBox.ButtonRole.AcceptRole)
    cancel_button = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(append_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked == cancel_button or clicked is None:
        return None
    return clicked == replace_button


def _notify_success(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def _notify_error(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.critical(parent, title, message)
