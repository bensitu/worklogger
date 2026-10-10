"""Opt-in layout checks for password recovery and local model operations."""

import json
import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from tests.presentation.test_local_models_presentation import FakeLocalModelHandlers
from worklogger.app.queries.local_model_queries import ListLocalModelsQuery
from worklogger.app.use_cases.local_models import LocalModelInventory
from worklogger.domain.local_model.models import LocalModelEntry, LocalModelListItem
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import (
    _,
    available_languages,
    get_language,
    set_language,
)
from worklogger.presentation.auth import (
    ChangePasswordDialog,
    RegisterDialog,
    ResetPasswordDialog,
)
from worklogger.presentation.local_models import LocalModelsDialog
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.theme import (
    configure_application_style,
    install_bundled_fonts,
)
from worklogger.presentation.theme.theme_engine import ThemeEngine
from worklogger.presentation.viewmodels import LocalModelManagerViewModel


class ModelAccountLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        configure_application_style()
        install_bundled_fonts()

    def setUp(self):
        self.language, self.stylesheet, self.palette = (
            get_language(),
            self.app.styleSheet(),
            self.app.palette(),
        )
        self.engine = ThemeEngine()

    def tearDown(self):
        set_language(self.language)
        self.app.setPalette(self.palette)
        self.app.setStyleSheet(self.stylesheet)

    def theme(self, dark):
        self.app.setPalette(self.engine.qt_palette(dark=dark))
        self.app.setStyleSheet(self.engine.application_stylesheet(dark=dark))

    def test_password_change_and_key_actions_fit_each_language(self):
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                self.theme(dark)
                for dialog_type in (
                    ChangePasswordDialog,
                    RegisterDialog,
                    ResetPasswordDialog,
                ):
                    self.check_credential_dialog(dialog_type, language, dark)

    def test_timer_end_correction_fits_dates_offsets_and_supported_languages(self):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from worklogger.presentation.widgets.end_timer import EndTimerDialog
        zone = ZoneInfo("America/New_York")
        start = datetime(2026, 11, 1, 0, 30, tzinfo=zone)
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                self.theme(dark)
                dialog = EndTimerDialog(start, start + timedelta(hours=18), zone)
                try:
                    dialog.end_input.setDateTime(datetime(2026, 11, 1, 1, 30))
                    dialog.show()
                    self.app.processEvents()
                    self.assertEqual(dialog.offset_combo.count(), 2)
                    for field in (dialog.end_input, dialog.offset_combo, dialog.status_label,
                                  dialog.end_button, dialog.cancel_button):
                        self.assertTrue(dialog.rect().contains(field.rect().translated(field.mapTo(dialog, QPoint()))))
                    self.assertGreaterEqual(dialog.end_input.width(), dialog.end_input.fontMetrics().horizontalAdvance(dialog.end_input.text()) + 40)
                    self.capture(dialog, f"{language}-timer-end-{'dark' if dark else 'light'}")
                finally:
                    dialog.hide()
                    dialog.deleteLater()

    def test_avatar_crop_controls_fit_localized_labels(self):
        from PySide6.QtGui import QImage
        from worklogger.presentation.widgets.avatar import AvatarCropDialog
        image = QImage(500, 350, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.green)
        for language, dark in (("en_US", False), ("zh_CN", True)):
            set_language(language)
            self.theme(dark)
            dialog = AvatarCropDialog(image)
            try:
                dialog.show()
                self.app.processEvents()
                dialog.zoom_slider.setValue(170)
                self.assertTrue(dialog.rect().contains(dialog.canvas.rect().translated(dialog.canvas.mapTo(dialog, QPoint()))))
                self.assertGreaterEqual(dialog.save_button.width(), dialog.save_button.fontMetrics().horizontalAdvance(dialog.save_button.text()) + 28)
                self.capture(dialog, f"{language}-avatar-crop-{'dark' if dark else 'light'}")
            finally:
                dialog.hide()
                dialog.deleteLater()

    def check_credential_dialog(self, dialog_type, language, dark):
        dialog = dialog_type()
        if hasattr(dialog, "username_input"):
            dialog.username_input.setText("sample.user")
        try:
            dialog.show()
            self.app.processEvents()
            self.capture(
                dialog,
                f"{language}-{dialog_type.__name__}-{'dark' if dark else 'light'}",
            )
            dialog.set_error(_("Save this recovery key before continuing."))
            dialog.mark_complete("example-recovery-key-not-a-credential-" + "x" * 24)
            self.app.processEvents()
            self.assertLessEqual(dialog.height(), 500)
            key_label = (
                dialog.recovery_key_result_label
                if isinstance(dialog, ResetPasswordDialog)
                else dialog.recovery_key_label
            )
            primary = (
                dialog.change_button
                if isinstance(dialog, ChangePasswordDialog)
                else dialog.reset_button
                if isinstance(dialog, ResetPasswordDialog)
                else dialog.register_button
            )
            for widget in (
                key_label,
                dialog.recovery_actions.copy_button,
                dialog.recovery_actions.save_button,
                primary,
            ):
                rect = widget.rect().translated(widget.mapTo(dialog, QPoint()))
                self.assertTrue(dialog.rect().contains(rect))
                if hasattr(widget, "icon"):
                    self.assertLessEqual(
                        widget.fontMetrics().horizontalAdvance(widget.text())
                        + (
                            widget.iconSize().width() + 4
                            if not widget.icon().isNull()
                            else 0
                        )
                        + 16,
                        widget.width(),
                    )
            self.capture(
                dialog,
                f"{language}-{dialog_type.__name__}-recovery-{'dark' if dark else 'light'}",
            )
        finally:
            dialog.hide()
            dialog.deleteLater()

    def test_model_details_and_actions_fit_inventory_states(self):
        root = Path(__file__).resolve().parents[2]
        entries = tuple(
            LocalModelEntry(**entry)
            for entry in json.loads(
                (root / "model_catalog.json").read_text(encoding="utf-8")
            )["models"]
        )
        inventory = LocalModelInventory(
            tuple(
                LocalModelListItem(
                    entry, index == 3, index in (1, 2, 3), index in (2, 3)
                )
                for index, entry in enumerate(entries)
            ),
            entries[3].id,
        )

        class Handlers(FakeLocalModelHandlers):
            def handle(self, command):
                return (
                    Result.success(inventory)
                    if isinstance(command, ListLocalModelsQuery)
                    else super().handle(command)
                )

        handlers = Handlers()
        model = LocalModelManagerViewModel(
            user_id=1,
            list_handler=handlers,
            refresh_handler=handlers,
            import_handler=handlers,
            download_handler=handlers,
            verify_handler=handlers,
            select_handler=handlers,
            delete_handler=handlers,
        )
        for language in available_languages():
            set_language(language)
            for dark in (False, True):
                self.theme(dark)
                dialog = LocalModelsDialog(model, job_runner=ImmediateJobRunner())
                try:
                    dialog.refresh()
                    dialog.show()
                    for width, height in ((800, 500), (1100, 700)):
                        dialog.resize(width, height)
                        for row in range(4):
                            dialog.model_list.setCurrentRow(row)
                            self.app.processEvents()
                            self.assertEqual(
                                (dialog.width(), dialog.height()), (width, height)
                            )
                            self.assertEqual(
                                dialog.details_scroll.horizontalScrollBar().maximum(), 0
                            )
                            self.assertEqual(
                                dialog.download_button.isEnabled(), row == 0
                            )
                            self.assertEqual(dialog.verify_button.isEnabled(), row != 0)
                            self.assertEqual(dialog.select_button.isEnabled(), row == 2)
                            for widget in (
                                dialog.model_list,
                                dialog.details_scroll,
                                dialog.download_button,
                                dialog.verify_button,
                                dialog.select_button,
                                dialog.delete_button,
                                dialog.refresh_button,
                                dialog.import_button,
                                dialog.close_button,
                            ):
                                rect = widget.rect().translated(
                                    widget.mapTo(dialog, QPoint())
                                )
                                self.assertTrue(
                                    dialog.rect().contains(rect),
                                    (language, width, row, widget),
                                )
                                if hasattr(widget, "text") and widget.text():
                                    self.assertLessEqual(
                                        widget.fontMetrics().horizontalAdvance(
                                            widget.text()
                                        )
                                        + (
                                            widget.iconSize().width() + 4
                                            if not widget.icon().isNull()
                                            else 0
                                        )
                                        + 16,
                                        widget.width(),
                                    )
                            self.capture(
                                dialog,
                                f"{language}-models-{'dark' if dark else 'light'}-{width}-{row}",
                            )
                    selected = dialog._selected_model_id()
                    dialog.refresh()
                    self.assertEqual(dialog._selected_model_id(), selected)
                    dialog._set_busy(True)
                    self.assertFalse(dialog.model_list.isEnabled())
                    self.assertFalse(dialog.select_button.isEnabled())
                    self.assertTrue(dialog.close_button.isEnabled())
                    dialog._set_busy(False)
                finally:
                    dialog.hide()
                    dialog.deleteLater()

    def capture(self, widget, name):
        directory = os.environ.get("WORKLOGGER_SCREENSHOTS")
        if directory:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(widget.grab().save(str(path / f"{name}.png")))
