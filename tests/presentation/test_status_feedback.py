from datetime import date
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from scripts.i18n.catalog_tools import extract_source_messages
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import available_languages, set_language
from worklogger.presentation.ai.dialog import AiAssistDialog
from worklogger.presentation.analytics.dialog import AnalyticsDialog
from worklogger.presentation.identity.dialog import IdentityDialog
from worklogger.presentation.local_models.dialog import LocalModelsDialog
from worklogger.presentation.notes.dialog import NoteEditorDialog
from worklogger.presentation.quick_logs.dialog import QuickLogDialog
from worklogger.presentation.reporting.dialog import ReportDialog, ReportTemplateDialog
from worklogger.presentation.user_management.dialog import UserManagementDialog
from worklogger.presentation.widgets.status_label import StatusLabel


class StatusFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self):
        set_language("en_US")

    def test_empty_status_is_hidden_and_errors_can_reappear(self):
        label = StatusLabel()
        self.assertTrue(label.isHidden())
        for _ in range(2):
            label.setText("Test error")
            self.assertFalse(label.isHidden())
            label.clear()
            self.assertEqual(label.text(), "")
            self.assertTrue(label.isHidden())
        label.deleteLater()

    def test_dialogs_clear_idle_status_after_load_and_error_recovery(self):
        day = date(2026, 5, 4)
        factories = (
            lambda model: AnalyticsDialog(model, day),
            lambda model: IdentityDialog(model),
            lambda model: LocalModelsDialog(model),
            lambda model: NoteEditorDialog(model, day),
            lambda model: QuickLogDialog(model, day),
            lambda model: UserManagementDialog(model),
            lambda model: ReportDialog(model, day),
        )
        state = SimpleNamespace(content="", message="", identities=(), providers=(),
                                inventory=SimpleNamespace(items=()))
        error = InfrastructureError("test_failure", "test_failure")
        for language in available_languages():
            set_language(language)
            for factory in factories:
                model = Mock()
                model.load.return_value = Result.success(state)
                dialog = factory(model)
                with self.subTest(language=language, dialog=type(dialog).__name__):
                    try:
                        # Rendering is covered by each dialog's presentation tests.
                        if hasattr(dialog, "set_state"):
                            dialog.set_state = Mock()
                        self.assertTrue(dialog.status_label.isHidden())
                        self.assertTrue(dialog.refresh())
                        self.assertEqual(dialog.status_label.text(), "")
                        self.assertTrue(dialog.status_label.isHidden())
                        model.load.return_value = Result.failure(error)
                        self.assertFalse(dialog.refresh())
                        self.assertEqual(dialog.last_error, error)
                        self.assertFalse(dialog.status_label.isHidden())
                        self.assertTrue(dialog.status_label.text())
                        model.load.return_value = Result.success(state)
                        self.assertTrue(dialog.refresh())
                        self.assertIsNone(dialog.last_error)
                        self.assertEqual(dialog.status_label.text(), "")
                        self.assertTrue(dialog.status_label.isHidden())
                    finally:
                        dialog.deleteLater()

    def test_ai_busy_feedback_clears_on_success_but_errors_remain_visible(self):
        class DeferredRunner:
            def submit(self, name, work, *, on_complete):
                from worklogger.app.job_runner import JobHandle
                self.complete = on_complete
                return JobHandle(job_id=name, cancel=lambda: None)

        for runner in (None, DeferredRunner()):
            state = SimpleNamespace(history=())
            model = Mock(available=True)
            model.initial_state.return_value = state
            model.send.return_value = Result.success(state)
            dialog = AiAssistDialog(model, date(2026, 5, 4), job_runner=runner)
            try:
                self.assertTrue(dialog.status_label.isHidden())
                dialog._set_error(InfrastructureError("test_failure", "test_failure"))
                self.assertFalse(dialog.status_label.isHidden())
                dialog.message_input.setText("Test request")
                self.assertTrue(dialog.send_current_message())
                if runner:
                    self.assertFalse(dialog.status_label.isHidden())
                    self.assertEqual(dialog.status_label.text(), "Sending...")
                    runner.complete(Result.success(state))
                self.assertIsNone(dialog.last_error)
                self.assertTrue(dialog.status_label.isHidden())
            finally:
                dialog.deleteLater()

    def test_template_refresh_clears_resolved_error(self):
        model = Mock()
        model.load_template.return_value = Result.failure(InfrastructureError("test_failure", "test_failure"))
        dialog = ReportTemplateDialog(model, "daily")
        self.assertFalse(dialog.refresh())
        self.assertFalse(dialog.status_label.isHidden())
        model.load_template.return_value = Result.success("Template")
        self.assertTrue(dialog.refresh())
        self.assertTrue(dialog.status_label.isHidden())
        dialog.deleteLater()

    def test_ready_is_no_longer_a_user_visible_message(self):
        self.assertNotIn("Ready", extract_source_messages())
