"""Inference lifecycle and model-selection behavior with injected engines."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from worklogger.app.ports import AIRequest
from worklogger.app.use_cases.ai import RewriteTextHandler
from worklogger.app.commands.ai_commands import RewriteTextCommand
from worklogger.domain.local_model.models import LocalModelEntry, LocalModelListItem, LocalModelFileStatus
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.ai.runtime import LocalInferenceRuntime


class LocalInferenceTests(unittest.TestCase):
    def _use_metal_factory(self, factory, *, probe=None):
        native = SimpleNamespace(Llama=factory, llama_supports_gpu_offload=probe or Mock(return_value=True))
        self.service._engine_factory = None
        self.enterContext(patch.dict("sys.modules", {"llama_cpp": native}))
        self.enterContext(patch("worklogger.infrastructure.ai.runtime_options.sys.platform", "darwin"))
        self.enterContext(patch("worklogger.infrastructure.ai.runtime_options.platform.machine", return_value="arm64"))

    def test_metal_load_and_execution_failures_retry_cpu_and_reuse_it(self):
        self.select()
        original_factory = self.service._engine_factory
        for stage in ("load", "execution"):
            with self.subTest(stage=stage):
                self.service.close()
                attempts = []
                def factory(**configuration):
                    attempts.append(configuration)
                    if configuration["n_gpu_layers"] != 0 and stage == "load":
                        raise RuntimeError("Private native diagnostic")
                    engine = original_factory(**configuration)
                    if configuration["n_gpu_layers"] != 0:
                        engine.create_chat_completion = Mock(side_effect=RuntimeError("Private native diagnostic"))
                    return engine
                self._use_metal_factory(factory)
                with self.assertLogs("worklogger.infrastructure.ai.runtime", level="WARNING") as log:
                    result = self.handler.handle(RewriteTextCommand(1, "Private work text"))
                self.assertTrue(result.ok, result.error)
                self.assertEqual(result.value.content, "Rewritten note")
                self.assertEqual(attempts[1], attempts[0] | {"n_gpu_layers": 0})
                self.assertNotIn("Private", "\n".join(log.output))
                if stage == "execution":
                    self.assertTrue(self.engines[-2].closed)
                self.assertFalse(self.engines[-1].closed)
                self.assertTrue(self.handler.handle(RewriteTextCommand(1, "Next note")).ok)
                self.assertEqual(len(attempts), 2)

    def test_cpu_failure_after_metal_failure_is_reported_without_additional_retries(self):
        self.select()
        original_factory = self.service._engine_factory
        for stage, code in (("load", "local_model_load_failed"), ("execution", "local_model_generation_failed")):
            with self.subTest(stage=stage):
                self.service.close()
                attempts = []
                def factory(**configuration):
                    attempts.append(configuration)
                    if stage == "load":
                        raise RuntimeError("Private native diagnostic")
                    engine = original_factory(**configuration)
                    engine.create_chat_completion = Mock(side_effect=RuntimeError("Private native diagnostic"))
                    return engine
                self._use_metal_factory(factory)
                with self.assertLogs("worklogger.infrastructure.ai.runtime", level="WARNING"):
                    result = self.handler.handle(RewriteTextCommand(1, "Private work text"))
                self.assertEqual(result.error.code, code)
                self.assertEqual([item["n_gpu_layers"] for item in attempts], [-1, 0])
                self.assertIsNone(self.service._engine)
                if stage == "execution":
                    self.assertTrue(all(engine.closed for engine in self.engines))
                self.assertNotIn("Private", str(result.error))

    def test_metal_cancellation_and_deadlines_do_not_retry_cpu(self):
        from worklogger.app.job_runner import CancellationToken
        self.select()
        original_factory = self.service._engine_factory
        for stage in ("load", "execution"):
            for reason in ("ai_rewrite_cancelled", "local_inference_timeout"):
                with self.subTest(stage=stage, reason=reason):
                    self.service.close()
                    attempts = []
                    token = CancellationToken()
                    now = [0]
                    def fail(**_kwargs):
                        if reason == "ai_rewrite_cancelled":
                            token.cancel()
                        else:
                            now[0] = 2
                        raise RuntimeError("Private native diagnostic")
                    def factory(**configuration):
                        attempts.append(configuration)
                        if stage == "load":
                            fail()
                        engine = original_factory(**configuration)
                        engine.create_chat_completion = Mock(side_effect=fail)
                        return engine
                    self._use_metal_factory(factory)
                    with patch("worklogger.infrastructure.ai.execution.monotonic", side_effect=lambda: now[0]):
                        result = self.service.generate(AIRequest(({"role": "user", "content": "Source"},),
                                                                  "sample", 1, token))
                    self.assertEqual(result.error.code, reason)
                    self.assertEqual(len(attempts), 1)
                    self.assertIsNone(self.service._engine)

    def test_metal_input_limits_and_empty_output_do_not_retry_cpu(self):
        self.select()
        original_factory = self.service._engine_factory
        for code in ("local_inference_context_limit", "local_model_empty_response"):
            with self.subTest(code=code):
                self.service.close()
                def factory(**configuration):
                    engine = original_factory(**configuration)
                    if code == "local_inference_context_limit":
                        engine.token_count = 10000
                    else:
                        engine.create_chat_completion = Mock(return_value={"choices": [{"message": {"content": ""}}]})
                    return engine
                create = Mock(side_effect=factory)
                self._use_metal_factory(create)
                result = self.handler.handle(RewriteTextCommand(1, "Source"))
                self.assertEqual(result.error.code, code)
                create.assert_called_once()

    def test_failed_metal_device_detection_uses_cpu(self):
        self.select()
        create = Mock(side_effect=self.service._engine_factory)
        self._use_metal_factory(create, probe=Mock(side_effect=RuntimeError("Private native diagnostic")))
        with self.assertLogs("worklogger.infrastructure.ai.runtime", level="WARNING"):
            result = self.handler.handle(RewriteTextCommand(1, "Source"))
        self.assertTrue(result.ok, result.error)
        create.assert_called_once()
        self.assertEqual(create.call_args.kwargs["n_gpu_layers"], 0)

    def test_runtime_options_use_metal_only_on_supported_apple_silicon_devices(self):
        from worklogger.infrastructure.ai.runtime_options import engine_options
        for platform, architecture, supported, expected in (
            ("darwin", "arm64", True, -1), ("darwin", "arm64", False, 0),
            ("darwin", "x86_64", True, 0), ("linux", "aarch64", True, 0),
            ("win32", "AMD64", False, 0),
        ):
            with self.subTest(platform=platform, architecture=architecture, supported=supported):
                options = engine_options(platform_name=platform, architecture=architecture,
                                         gpu_offload_supported=supported, cpu_count=20)
                self.assertEqual(options, dict(n_gpu_layers=expected, n_threads=8, n_threads_batch=16))
        self.assertEqual(engine_options(cpu_count=1)["n_threads"], 1)
        self.assertEqual(engine_options(cpu_count=4)["n_threads"], 3)
        with (patch("worklogger.infrastructure.ai.runtime_options.os.process_cpu_count", return_value=4, create=True),
              patch("worklogger.infrastructure.ai.runtime_options.os.sched_getaffinity", return_value={0, 1}, create=True)):
            self.assertEqual(engine_options()["n_threads_batch"], 1)

    def test_engine_loading_uses_detected_gpu_capability_and_falls_back_without_a_device(self):
        from unittest.mock import Mock
        self.select()
        native = SimpleNamespace(Llama=self.service._engine_factory, llama_supports_gpu_offload=Mock(return_value=True))
        self.service._engine_factory = None
        with (patch.dict("sys.modules", {"llama_cpp": native}),
              patch("worklogger.infrastructure.ai.runtime_options.sys.platform", "darwin"),
              patch("worklogger.infrastructure.ai.runtime_options.platform.machine", return_value="arm64")):
            self.assertTrue(self.handler.handle(RewriteTextCommand(1, "Original note")).ok)
            self.assertEqual(self.engines[-1].configuration["n_gpu_layers"], -1)
            self.service.close()
            native.llama_supports_gpu_offload.return_value = False
            self.assertTrue(self.handler.handle(RewriteTextCommand(1, "Original note")).ok)
            self.assertEqual(self.engines[-1].configuration["n_gpu_layers"], 0)
        self.assertEqual(native.llama_supports_gpu_offload.call_count, 2)

    def test_cancellation_reaches_verification_and_generation(self):
        from worklogger.app.job_runner import CancellationToken
        from worklogger.domain.shared.errors import CancellationError
        self.select()
        token = CancellationToken()
        def verify(model, *, is_cancelled):
            token.cancel()
            self.assertTrue(is_cancelled())
            return Result.success(LocalModelFileStatus(model, True, True))
        self.store.verify_model = verify
        result = self.handler.handle(RewriteTextCommand(1, "Original note"), cancellation_token=token)
        self.assertIsInstance(result.error, CancellationError)
        self.assertEqual(self.engines, [])
        token = CancellationToken()
        self.store.verify_model = lambda model, **kwargs: Result.success(LocalModelFileStatus(model, True, True))
        self.assertTrue(self.handler.handle(RewriteTextCommand(1, "Warm up")).ok)
        engine = self.engines[-1]
        def completion(**kwargs):
            token.cancel()
            kwargs["logits_processor"]([], [])
        engine.create_chat_completion = completion
        result = self.handler.handle(RewriteTextCommand(1, "Original note"), cancellation_token=token)
        self.assertIsInstance(result.error, CancellationError)
        self.assertTrue(engine.closed)

    def test_tokenization_deadline_prevents_starting_completion(self):
        self.select()
        self.assertTrue(self.handler.handle(RewriteTextCommand(1, "Warm up")).ok)
        engine = self.engines[-1]
        with patch("worklogger.infrastructure.ai.execution.monotonic", side_effect=[0, 0, 0, 0, 0, 2, 2, 2]), \
             patch.object(engine, "create_chat_completion") as completion:
            result = self.service.generate(AIRequest(messages=({"role": "user", "content": "Sample"},),
                                                     model="sample", timeout_seconds=1))
        self.assertEqual(result.error.code, "local_inference_timeout")
        completion.assert_not_called()

    def setUp(self):
        self.values = {"local_model_active_id": "sample", "local_model_enabled": "1", "ai_assist_enabled": "1"}
        self.settings = SimpleNamespace(get=lambda user, key, default=None: self.values.get(key, default))
        self.entry = LocalModelEntry("sample", "Sample", "sample.gguf", context_length=512, max_output_tokens=64)
        self.store = SimpleNamespace(verify_model=lambda model, **kwargs: Result.success(LocalModelFileStatus(model, True, True)),
            model_path=lambda model: Path(__file__))
        self.engines = []
        class Engine:
            def __init__(engine, **kwargs):
                self.engines.append(engine)
                engine.configuration = kwargs
                engine.closed = False
                engine.token_count = 4
            def tokenize(engine, data, **kwargs):
                return [1] * engine.token_count
            def create_chat_completion(engine, **kwargs):
                engine.last_request = kwargs
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

    def test_rewriting_uses_compact_prompts_without_changing_generation_limits(self):
        from worklogger.app.use_cases.text_prompts import rewrite_messages
        self.select()
        source = "- [x] Reviewed ticket T-12\n- [ ] Follow up"
        result = self.handler.handle(RewriteTextCommand(1, source, "daily_note", "en_US"))
        self.assertTrue(result.ok, result.error)
        request = self.engines[-1].last_request
        self.assertEqual(tuple(request["messages"]), rewrite_messages(
            content=source, context="daily_note", compact=True))
        self.assertEqual(request["temperature"], 0.2)
        self.assertEqual(request["max_tokens"], 64)

    def test_runtime_context_preference_reloads_only_when_effective_capacity_changes(self):
        from dataclasses import replace
        self.select(replace(self.entry, context_length=131072, max_output_tokens=8192))
        command = RewriteTextCommand(1, "Original note")
        self.assertTrue(self.handler.handle(command).ok)
        self.assertEqual(self.engines[-1].configuration["n_ctx"], 8192)
        self.assertEqual(self.engines[-1].last_request["max_tokens"], 2048)
        for tokens in (16384, 65536, 131072):
            self.values["local_model_context_tokens"] = str(tokens)
            previous = self.engines[-1]
            self.assertTrue(self.handler.handle(command).ok)
            self.assertTrue(previous.closed)
            self.assertEqual(self.engines[-1].configuration["n_ctx"], tokens)
        count = len(self.engines)
        self.values["local_model_context_tokens"] = "262144"
        self.assertTrue(self.handler.handle(command).ok)
        self.assertEqual(len(self.engines), count)
        self.assertEqual(self.engines[-1].configuration["n_ctx"], 131072)
        self.select(replace(self.entry, context_length=32768))
        self.assertTrue(self.handler.handle(command).ok)
        self.assertEqual(self.engines[-1].configuration["n_ctx"], 32768)
        self.assertEqual(self.values["local_model_context_tokens"], "262144")
        self.values["local_model_context_tokens"] = "invalid"
        self.assertTrue(self.handler.handle(command).ok)
        self.assertEqual(self.engines[-1].configuration["n_ctx"], 8192)

    def test_time_and_context_limits_return_safe_errors(self):
        self.select()
        request = AIRequest(({"role": "user", "content": "Private example"},), "default", -1)
        result = self.service.generate(request)
        self.assertEqual(result.error.code, "local_inference_timeout")
        self.assertTrue(self.handler.handle(RewriteTextCommand(1, "Warm up")).ok)
        self.engines[-1].token_count = 10000
        result = self.service.generate(AIRequest(request.messages, "default", 30))
        self.assertEqual(result.error.code, "local_inference_context_limit")
        self.assertNotIn("Private example", repr(result.error))

    def test_verification_or_loading_failure_cannot_produce_a_result(self):
        self.select()
        self.store.verify_model = lambda model, **kwargs: Result.success(LocalModelFileStatus(model, True, False, "local_model_hash_mismatch"))
        result = self.handler.handle(RewriteTextCommand(1, "Original note"))
        self.assertEqual(result.error.code, "local_model_hash_mismatch")
        self.assertEqual(self.engines, [])
        self.store.verify_model = lambda model, **kwargs: Result.success(LocalModelFileStatus(model, True, True))
        self.service._engine_factory = lambda **kwargs: (_ for _ in ()).throw(OSError("Private diagnostic"))
        result = self.handler.handle(RewriteTextCommand(1, "Original note"))
        self.assertEqual(result.error.code, "local_model_load_failed")
        self.assertNotIn("Private diagnostic", repr(result.error))
