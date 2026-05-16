from __future__ import annotations

from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from worklogger.app.commands.ai_commands import SendAiChatMessageCommand
from worklogger.app.queries.ai_queries import BuildAiContextQuery
from worklogger.app.use_cases.ai import AiChatResult, AiContextResult
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
