from __future__ import annotations

from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from worklogger.app.commands.ai_commands import SendAiChatMessageCommand
from worklogger.app.queries.ai_queries import BuildAiContextQuery
from worklogger.app.use_cases.ai import AiChatHandler, AiChatResult, AiContextResult
from worklogger.app.job_runner import JobHandle
from worklogger.domain.shared.result import Result
from worklogger.presentation.ai import AiAssistDialog
from worklogger.presentation.job_runner import ImmediateJobRunner
from worklogger.presentation.viewmodels import AiAssistViewModel


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class FakeChatHandler:
    def __init__(self) -> None:
        self.commands: list[SendAiChatMessageCommand] = []

    def handle(self, command: SendAiChatMessageCommand) -> Result[AiChatResult]:
        self.commands.append(command)
        return Result.success(
            AiChatResult(
                reply="reply",
                history=(
                    *command.history,
                    {"role": "user", "content": command.message},
                    {"role": "assistant", "content": "reply"},
                ),
            )
        )


class FakeContextHandler:
    def __init__(self) -> None:
        self.queries: list[BuildAiContextQuery] = []

    def handle(self, query: BuildAiContextQuery) -> Result[AiContextResult]:
        self.queries.append(query)
        return Result.success(AiContextResult("built context"))


class AiAssistPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = _app()

    def test_unconfigured_backend_disables_send_without_submitting(self) -> None:
        dialog = AiAssistDialog(
            AiAssistViewModel(user_id=1, chat_handler=AiChatHandler()), date(2026, 5, 4),
        )
        self.assertFalse(dialog.send_button.isEnabled())
        self.assertFalse(dialog.message_input.isEnabled())
        self.assertFalse(dialog.send_current_message())
        self.assertIsNone(dialog.last_error)

    def test_pending_request_prevents_dialog_close(self) -> None:
        class DeferredRunner:
            def submit(self, name, work, *, on_complete):
                self.work = work
                self.complete = on_complete
                return JobHandle(job_id=name, cancel=lambda: None)

        runner = DeferredRunner()
        dialog = AiAssistDialog(
            AiAssistViewModel(user_id=1, chat_handler=FakeChatHandler()),
            date(2026, 5, 4), job_runner=runner,
        )
        dialog.show()
        dialog.message_input.setText("Summarize")
        self.assertTrue(dialog.send_current_message())
        dialog.close()
        self.assertTrue(dialog.isVisible())
        dialog.reject()
        self.assertTrue(dialog.isVisible())
        runner.complete(runner.work(None))
        self.assertTrue(dialog.send_button.isEnabled())
        dialog.close()
        self.assertFalse(dialog.isVisible())

    def test_dialog_sends_selected_day_context(self) -> None:
        chat = FakeChatHandler()
        context = FakeContextHandler()
        dialog = AiAssistDialog(
            AiAssistViewModel(
                user_id=1,
                chat_handler=chat,
                context_handler=context,
            ),
            date(2026, 5, 4),
            job_runner=ImmediateJobRunner(),
        )

        dialog.message_input.setText("Summarize")
        self.assertTrue(dialog.send_current_message())

        self.assertEqual(context.queries[0].selected_day, date(2026, 5, 4))
        self.assertEqual(chat.commands[0].context, "built context")
        self.assertIn("Assistant: reply", dialog.transcript.toPlainText())

    def test_dialog_can_send_through_job_runner(self) -> None:
        chat = FakeChatHandler()
        context = FakeContextHandler()
        dialog = AiAssistDialog(
            AiAssistViewModel(
                user_id=1,
                chat_handler=chat,
                context_handler=context,
            ),
            date(2026, 5, 4),
            job_runner=ImmediateJobRunner(),
        )

        dialog.message_input.setText("Summarize")
        self.assertTrue(dialog.send_current_message())

        self.assertIn("Assistant: reply", dialog.transcript.toPlainText())


if __name__ == "__main__":
    unittest.main()
