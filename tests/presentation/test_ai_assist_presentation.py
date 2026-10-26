from __future__ import annotations

from datetime import date
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from worklogger.app.commands.ai_commands import SendAiChatMessageCommand
from worklogger.app.queries.ai_queries import BuildAiContextQuery
from worklogger.app.use_cases.ai import AiChatHandler, AiChatResult, AiContextResult
from worklogger.app.job_runner import CancellationToken, JobHandle
from worklogger.app.ports import AIResponse
from worklogger.domain.shared.result import Result
from worklogger.presentation.ai import AiAssistDialog
from tests.job_runner import ImmediateJobRunner
from worklogger.presentation.viewmodels import AiAssistViewModel


def _app() -> QApplication:
    existing = QApplication.instance()
    if existing is not None:
        return existing
    return QApplication([])


class FakeChatHandler:
    def __init__(self) -> None:
        self.commands: list[SendAiChatMessageCommand] = []

    def handle(self, command: SendAiChatMessageCommand, cancellation_token=None) -> Result[AiChatResult]:
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


class DeferredRunner:
    def submit(self, name, work, *, on_complete):
        self.work = work
        self.complete = on_complete
        self.token = CancellationToken()
        return JobHandle(job_id=name, cancel=self.token.cancel)


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

    def test_cancellation_skips_context_and_generation_at_request_boundaries(self):
        for stage in ("before_context", "during_context"):
            with self.subTest(stage=stage):
                token = CancellationToken()
                chat = FakeChatHandler()

                class Context(FakeContextHandler):
                    def handle(self, query):
                        result = super().handle(query)
                        token.cancel()
                        return result

                context = Context()
                model = AiAssistViewModel(user_id=1, chat_handler=chat, context_handler=context)
                state = model.initial_state()
                if stage == "before_context":
                    token.cancel()
                result = model.send(state, "Summarize", selected_day=date(2026, 5, 4),
                                    cancellation_token=token)
                self.assertEqual(result.error.code, "ai_chat_cancelled")
                self.assertEqual(len(context.queries), int(stage == "during_context"))
                self.assertEqual(chat.commands, [])
                self.assertEqual(state.history, ())

    def test_dialog_cancellation_reaches_gateway_and_ignores_its_late_reply(self):
        runner = DeferredRunner()

        class Gateway:
            def generate(self, request):
                self.request = request
                dialog.processing_progress.cancel_button.click()
                return Result.success(AIResponse("Late reply", "test"))

        gateway = Gateway()
        model = AiAssistViewModel(user_id=1, chat_handler=AiChatHandler(gateway))
        dialog = AiAssistDialog(model, date(2026, 5, 4), job_runner=runner)
        self.addCleanup(dialog.deleteLater)
        finished = QSignalSpy(dialog._processing_task.finished)
        initial_state = dialog.state
        dialog.message_input.setText("Keep this question")
        self.assertTrue(dialog.send_current_message())
        result = runner.work(runner.token)
        self.assertIs(gateway.request.cancellation_token, runner.token)
        self.assertTrue(runner.token.is_cancelled())
        self.assertEqual(result.error.code, "ai_chat_cancelled")
        self.assertEqual(finished.count(), 1)
        dialog.message_input.setText("Next question")
        runner.complete(result)
        self.assertEqual(finished.count(), 1)
        self.assertEqual(dialog.state, initial_state)
        self.assertEqual(dialog.transcript.toPlainText(), "")
        self.assertEqual(dialog.message_input.text(), "Next question")
        self.assertIsNone(dialog._pending_handle)
        self.assertIsNone(dialog.last_error)
        self.assertTrue(dialog.send_button.isEnabled())
        self.assertTrue(dialog.close_button.isEnabled())

    def test_optional_chat_token_rejects_success_returned_after_cancellation(self):
        class Chat(FakeChatHandler):
            def handle(self, command, cancellation_token=None):
                self.token = cancellation_token
                result = super().handle(command, cancellation_token)
                if cancellation_token is not None:
                    cancellation_token.cancel()
                return result

        for token in (None, CancellationToken()):
            with self.subTest(token_supplied=token is not None):
                chat = Chat()
                model = AiAssistViewModel(user_id=1, chat_handler=chat)
                state = model.initial_state()
                result = (model.send(state, "Summarize") if token is None else
                          model.send(state, "Summarize", cancellation_token=token))
                self.assertIs(chat.token, token)
                if token is None:
                    self.assertTrue(result.ok)
                    self.assertEqual(result.value.history[-1]["content"], "reply")
                else:
                    self.assertEqual(result.error.code, "ai_chat_cancelled")
                self.assertEqual(state.history, ())

    def test_rejected_request_start_leaves_the_dialog_usable(self):
        from unittest.mock import patch
        dialog = AiAssistDialog(AiAssistViewModel(user_id=1, chat_handler=FakeChatHandler()),
                                date(2026, 5, 4))
        dialog.message_input.setText("Summarize")
        with patch.object(dialog._processing_task, "run", return_value=False):
            self.assertFalse(dialog.send_current_message())
        self.assertTrue(dialog.send_button.isEnabled())
        self.assertIsNone(dialog._pending_handle)
        dialog.show()
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
