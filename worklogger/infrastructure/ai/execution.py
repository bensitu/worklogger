"""Cooperative cancellation and deadlines for native inference execution."""

from contextlib import contextmanager
from time import monotonic


class InferenceControl:
    def __init__(self, request):
        self.deadline = monotonic() + max(0.0, request.timeout_seconds)
        self.token = request.cancellation_token
        self.reason = ""

    def interrupted(self):
        if self.token is not None and self.token.is_cancelled():
            self.reason = "ai_rewrite_cancelled"
        elif monotonic() >= self.deadline:
            self.reason = "local_inference_timeout"
        return bool(self.reason)

    def check(self):
        if self.interrupted():
            raise InterruptedError(self.reason)

    @contextmanager
    def acquire(self, lock):
        self.check()
        while not lock.acquire(timeout=0.1):
            self.check()
        try:
            self.check()
            yield
        finally:
            lock.release()

    @contextmanager
    def native_callback(self, engine):
        context = getattr(getattr(engine, "_ctx", None), "ctx", None)
        if context is None:
            yield
            return
        from llama_cpp import llama_cpp

        callback = llama_cpp.ggml_abort_callback(lambda _data: self.interrupted())
        llama_cpp.llama_set_abort_callback(context, callback, None)
        try:
            yield
        finally:
            llama_cpp.llama_set_abort_callback(context, llama_cpp.ggml_abort_callback(), None)
