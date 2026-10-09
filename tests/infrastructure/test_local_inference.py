"""Inference lifecycle and model-selection behavior with injected engines."""

from pathlib import Path
from types import SimpleNamespace
import unittest

from worklogger.app.ports import AIRequest
from worklogger.app.use_cases.ai import RewriteTextHandler
from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.domain.local_model.models import LocalModelEntry, LocalModelListItem, LocalModelFileStatus
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.ai.runtime import LocalInferenceRuntime


class LocalInferenceTests(unittest.TestCase):
    def setUp(self):
        self.values = {"local_model_active_id": "sample", "local_model_enabled": "1", "ai_assist_enabled": "1"}
        self.settings = SimpleNamespace(get=lambda user, key, default=None: self.values.get(key, default))
        self.entry = LocalModelEntry("sample", "Sample", "sample.gguf", context_length=512, max_output_tokens=64)
        self.store = SimpleNamespace(verify_model=lambda model: Result.success(LocalModelFileStatus(model, True, True)),
            model_path=lambda model: Path(__file__))
        self.engines = []
        class Engine:
            def __init__(engine, **kwargs):
                self.engines.append(engine)
                engine.closed = False
                engine.token_count = 4
            def tokenize(engine, data, **kwargs):
                return [1] * engine.token_count
            def create_chat_completion(engine, **kwargs):
                kwargs["logits_processor"]([], [])
                return {"choices": [{"message": {"content": "Rewritten note"}}]}
            def close(engine):
                engine.closed = True
        self.service = LocalInferenceRuntime(store=self.store, settings=self.settings, user_id=1, engine_factory=Engine)
        self.addCleanup(self.service.close)
        self.handler = RewriteTextHandler(self.service)

    def select(self, entry=None, verified=True):
        entry = entry or self.entry
        self.values["local_model_active_id"] = entry.id
        self.service.update_inventory(SimpleNamespace(active_model_id=entry.id,
            items=(LocalModelListItem(entry, True, True, verified),)))

    def test_selection_preferences_and_engine_reuse_release(self):
        self.assertFalse(self.handler.available)
        self.select()
        self.assertTrue(self.handler.available)
        for _ in range(2):
            self.assertEqual(self.handler.handle(RewriteTextCommand(1, "Original note")).value.content, "Rewritten note")
        self.assertEqual(len(self.engines), 1)
        self.values["local_model_enabled"] = "0"
        self.assertFalse(self.handler.available)
        self.assertFalse(self.handler.handle(RewriteTextCommand(1, "Original note")).ok)
        self.values["local_model_enabled"] = "1"
        self.select(LocalModelEntry("second", "Second", "second.gguf"))
        self.assertTrue(self.handler.handle(RewriteTextCommand(1, "Original note")).ok)
        self.assertTrue(self.engines[0].closed)
        self.service.release_model("second")
        self.assertTrue(self.engines[1].closed)
        self.select(verified=False)
        self.assertFalse(self.handler.available)

    def test_time_and_context_limits_return_safe_errors(self):
        self.select()
        request = AIRequest(({"role": "user", "content": "Private example"},), "default", -1)
        result = self.service.generate(request)
        self.assertEqual(result.error.code, "local_inference_timeout")
        self.engines[0].token_count = 10000
        result = self.service.generate(AIRequest(request.messages, "default", 30))
        self.assertEqual(result.error.code, "local_inference_context_limit")
        self.assertNotIn("Private example", repr(result.error))

    def test_verification_or_loading_failure_cannot_produce_a_result(self):
        self.select()
        self.store.verify_model = lambda model: Result.success(LocalModelFileStatus(model, True, False, "local_model_hash_mismatch"))
        result = self.handler.handle(RewriteTextCommand(1, "Original note"))
        self.assertEqual(result.error.code, "local_model_hash_mismatch")
        self.assertEqual(self.engines, [])
        self.store.verify_model = lambda model: Result.success(LocalModelFileStatus(model, True, True))
        self.service._engine_factory = lambda **kwargs: (_ for _ in ()).throw(OSError("Private diagnostic"))
        result = self.handler.handle(RewriteTextCommand(1, "Original note"))
        self.assertEqual(result.error.code, "local_model_load_failed")
        self.assertNotIn("Private diagnostic", repr(result.error))
