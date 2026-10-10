"""Account-scoped, lazy native inference for verified local model files."""

from dataclasses import asdict
from importlib.util import find_spec
import os
from threading import RLock
from time import monotonic

from worklogger.config.constants import (
    AI_ASSIST_ENABLED_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
    LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
)
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.ai.local import LocalModelGateway


class LocalInferenceRuntime:
    def __init__(self, *, store, settings, user_id, enabled=True, engine_factory=None):
        self.store = store
        self._settings = settings
        self._user_id = user_id
        self._enabled = enabled
        self.backend_available = enabled and (
            engine_factory is not None or find_spec("llama_cpp") is not None
        )
        self._engine_factory = engine_factory
        self._entry = None
        self._reason = (
            "local_model_not_selected"
            if self.backend_available
            else "local_inference_dependency_missing"
        )
        self._engine = None
        self._engine_key = None
        self._lock = RLock()
        self._state_lock = RLock()

    def _preference(self, key, default="1"):
        return str(
            self._settings.get(self._user_id, key, default) or ""
        ).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def available(self):
        try:
            with self._state_lock:
                entry = self._entry
            return bool(
                self.backend_available
                and entry
                and self._preference(LOCAL_MODEL_ENABLED_SETTING_KEY)
                and self._preference(AI_ASSIST_ENABLED_SETTING_KEY)
                and self._settings.get(self._user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY)
                == entry.id
            )
        except Exception:
            return False

    @property
    def reason(self):
        try:
            return self._runtime_reason()
        except Exception:
            return "settings_load_failed"

    def _runtime_reason(self):
        if not self._enabled:
            return "ai_service_disabled"
        if not self.backend_available:
            return "local_inference_dependency_missing"
        if not self._preference(LOCAL_MODEL_ENABLED_SETTING_KEY):
            return "local_model_disabled"
        if not self._preference(AI_ASSIST_ENABLED_SETTING_KEY):
            return "ai_assist_disabled"
        with self._state_lock:
            if (
                self._entry is not None
                and self._settings.get(self._user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY)
                != self._entry.id
            ):
                return "local_model_not_selected"
            return (
                self._reason or "local_model_not_selected"
                if self._entry is None
                else self._reason
            )

    def update_inventory(self, inventory):
        if inventory.active_model_id != self._settings.get(self._user_id, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY):
            return False
        item = next(
            (
                item
                for item in inventory.items
                if item.entry.id == inventory.active_model_id
            ),
            None,
        )
        with self._state_lock:
            self._entry = (
                item.entry if item and item.available and item.verified else None
            )
            self._reason = (
                ""
                if self._entry
                else item.reason
                if item and item.reason
                else "local_model_not_selected"
            )
        return True

    def generate(self, request):
        try:
            with self._lock:
                if not self.available:
                    return Result.failure(ValidationError(self.reason, self.reason))
                with self._state_lock:
                    entry = self._entry
                verified = self.store.verify_model(entry.id)
                if not verified.ok or not verified.value.verified:
                    code = (
                        verified.value.reason
                        if verified.ok
                        else "local_model_verify_failed"
                    )
                    return Result.failure(ValidationError(code, code))
                path = self.store.model_path(entry.id)
                stat = path.stat()
                context = min(8192, max(512, entry.context_length))
                key = (entry.id, stat.st_mtime_ns, stat.st_size, entry.sha256, context)
                started = monotonic()
                if self._engine_key != key:
                    self._close_engine()
                    factory = self._engine_factory
                    if factory is None:
                        try:
                            from llama_cpp import Llama

                            factory = Llama
                        except (ImportError, OSError):
                            self.backend_available = False
                            return Result.failure(
                                InfrastructureError(
                                    "local_inference_dependency_missing",
                                    "local_inference_dependency_missing",
                                )
                            )
                    try:
                        self._engine = factory(
                            model_path=str(path),
                            n_ctx=context,
                            n_gpu_layers=0,
                            n_threads=max(1, min(8, (os.cpu_count() or 2) - 1)),
                            verbose=False,
                        )
                        self._engine_key = key
                    except Exception:
                        self._close_engine()
                        return Result.failure(
                            InfrastructureError(
                                "local_model_load_failed", "local_model_load_failed"
                            )
                        )

                failure = []

                def generate(messages, output_limit):
                    def check_deadline(_tokens, scores):
                        if monotonic() - started > request.timeout_seconds:
                            failure.append("local_inference_timeout")
                            raise TimeoutError("local_inference_timeout")
                        return scores

                    check_deadline(None, None)
                    tokens = self._engine.tokenize(
                        "\n".join(message["content"] for message in messages).encode(
                            "utf-8"
                        ),
                        add_bos=False,
                    )
                    budget = context - len(tokens) - 256
                    if budget <= 0:
                        failure.append("local_inference_context_limit")
                        raise ValueError("local_inference_context_limit")

                    class Processors(list):
                        def __call__(self, tokens, scores):
                            for processor in self:
                                scores = processor(tokens, scores)
                            return scores

                    result = self._engine.create_chat_completion(
                        messages=list(messages),
                        max_tokens=min(output_limit, budget),
                        temperature=0.2,
                        logits_processor=Processors([check_deadline]),
                    )
                    return result["choices"][0]["message"]["content"]

                result = LocalModelGateway(
                    generator=generate,
                    model_id=entry.id,
                    catalog_entry=asdict(entry),
                    max_output_tokens=min(2048, max(1, entry.max_output_tokens)),
                ).generate(request)
                if failure:
                    return Result.failure(InfrastructureError(failure[0], failure[0]))
                if not result.ok:
                    return Result.failure(
                        InfrastructureError(result.error.code, result.error.code)
                    )
                return result
        except Exception:
            return Result.failure(
                InfrastructureError(
                    "local_model_generation_failed", "local_model_generation_failed"
                )
            )

    def _close_engine(self):
        engine, self._engine = self._engine, None
        self._engine_key = None
        if engine is not None:
            engine.close()

    def close(self):
        with self._lock:
            self._close_engine()

    def release_model(self, model_id):
        with self._lock:
            if self._engine_key and self._engine_key[0] == model_id:
                self._close_engine()
