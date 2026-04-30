"""AI API integration — OpenAI-compatible + Anthropic, stdlib only."""

from __future__ import annotations
import json
import threading
import socket
import time
import urllib.parse
import urllib.request
import urllib.error
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal

# Thread-safe callback bridge helpers.


class _CallbackInvoker(QObject):
    """Helper object to safely invoke callbacks from any thread."""
    done_signal = Signal(str)
    error_signal = Signal(str, str)
    status_signal = Signal(str)

    def __init__(self, on_done, on_error, on_status):
        super().__init__()
        self.on_done = on_done
        self.on_error = on_error
        self.on_status = on_status
        self.done_signal.connect(self._on_done)
        self.error_signal.connect(self._on_error)
        self.status_signal.connect(self._on_status)

    def detach_callbacks(self) -> None:
        """Drop callback references after the UI no longer wants updates."""
        self.on_done = lambda _text: None
        self.on_error = lambda _short, _detail: None
        self.on_status = None

    def _on_done(self, text):
        self.on_done(text)

    def _on_error(self, short, detail):
        self.on_error(short, detail)

    def _on_status(self, msg):
        if self.on_status:
            self.on_status(msg)


# Keep references to short-lived test invokers so they are not garbage-collected
# while the background test thread is running. Entries are removed on done/error.
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
AI_REQUEST_RETRY_DELAYS = (0.5, 1.0)
_test_invokers: list[_CallbackInvoker] = []
_test_invokers_lock = threading.Lock()


# Internal helpers.

def _sanitize_header(value: str) -> str:
    return ''.join(c for c in value if 32 <= ord(c) <= 126)


def _read_limited_response(resp) -> bytes:
    body = resp.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("AI response too large (> 4MB)")
    return body


def _is_retryable_http_error(exc: urllib.error.HTTPError) -> bool:
    return exc.code == 429 or 500 <= exc.code <= 599


def _read_json_with_retries(
    req: urllib.request.Request,
    *,
    timeout: float,
    is_cancelled: Callable[[], bool],
    on_wait: Callable[[], None],
) -> dict:
    attempts = len(AI_REQUEST_RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                on_wait()
                body = _read_limited_response(resp)
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            if not _is_retryable_http_error(exc) or attempt >= attempts - 1:
                raise
            if is_cancelled():
                raise
            time.sleep(AI_REQUEST_RETRY_DELAYS[attempt])
        except (urllib.error.URLError, TimeoutError):
            if attempt >= attempts - 1:
                raise
            if is_cancelled():
                raise
            time.sleep(AI_REQUEST_RETRY_DELAYS[attempt])
    return {}


def _retain_test_invoker(invoker: _CallbackInvoker) -> None:
    with _test_invokers_lock:
        _test_invokers.append(invoker)


def _release_test_invoker(invoker: _CallbackInvoker) -> None:
    with _test_invokers_lock:
        try:
            _test_invokers.remove(invoker)
        except ValueError:
            pass


def _resolve_endpoint(base_url: str) -> tuple[str, bool]:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("API Base URL is not configured.")
    low = base.lower()
    if low.endswith("/v1/messages"):
        return base, True
    if low.endswith("/chat/completions"):
        return base, False
    if "anthropic" in low:
        return base + "/v1/messages", True
    return base + "/chat/completions", False


def _build_request(url: str, is_anthropic: bool,
                   api_key: str, model: str,
                   messages: list[dict], max_tokens: int) -> urllib.request.Request:
    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }).encode('utf-8')
    safe_key = _sanitize_header(api_key)
    if is_anthropic:
        headers = {
            "Content-Type": "application/json",
            "x-api-key": safe_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {safe_key}",
        }
    return urllib.request.Request(url, data=payload, headers=headers, method="POST")


def _extract_text(data: dict, is_anthropic: bool) -> str:
    if is_anthropic:
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    choices = data.get("choices", [])
    if not choices:
        return ""
    msg = choices[0].get("message", {})
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content or "")


def _read_api_error(exc: urllib.error.HTTPError) -> str:
    try:
        body = _read_limited_response(exc).decode("utf-8", errors="replace")
        obj = json.loads(body)
        msg = (obj.get("error") or {}).get("message", "")
        if not msg:
            msg = obj.get("message", "")
        return msg.strip()
    except Exception:
        return ""


def _classify(exc: Exception, api_key: str, base_url: str, model: str) -> tuple[str, str]:
    if not api_key:
        return "API Key is not set.", "Please enter your API Key in Settings → AI."
    if not base_url:
        return "API Base URL is not set.", "Please enter the API Base URL in Settings → AI."
    if not model:
        return "Model name is not set.", "Please enter a model name in Settings → AI."

    if isinstance(exc, urllib.error.HTTPError):
        code = exc.code
        api_msg = _read_api_error(exc)
        detail = f"HTTP {code}"
        if api_msg:
            detail += f"\n{api_msg}"
        if code == 401:
            short = "Authentication failed (HTTP 401) — invalid API key."
        elif code == 403:
            short = "Access denied (HTTP 403) — check API key permissions."
        elif code == 404:
            if "model" in api_msg.lower():
                short = f"Model not found (HTTP 404) — '{model}' may be wrong."
            else:
                short = "Endpoint not found (HTTP 404) — check API Base URL."
            detail += f"\nURL: {exc.url}"
        elif code == 422:
            short = "Invalid request (HTTP 422) — check model name or parameters."
        elif code == 429:
            short = "Rate limit exceeded (HTTP 429) — too many requests."
        elif code >= 500:
            short = f"Server error (HTTP {code}) — the AI provider is having issues."
        else:
            short = f"HTTP error {code}."
        return short, detail

    if isinstance(exc, urllib.error.URLError):
        reason = str(exc.reason).lower()
        if "timed out" in reason or "timeout" in reason:
            return "Request timed out.", f"The server did not respond in time.\nBase URL: {base_url}"
        if "connection refused" in reason:
            return "Connection refused.", f"The server actively refused the connection.\nBase URL: {base_url}"
        if any(x in reason for x in ("name or service not known", "nodename", "getaddrinfo", "name resolution")):
            return "Cannot resolve host — check the API Base URL.", f"DNS lookup failed for: {base_url}"
        return "Network error.", f"{exc.reason}\nBase URL: {base_url}"

    if isinstance(exc, TimeoutError):
        return "Request timed out.", f"The server did not respond in time.\nBase URL: {base_url}"

    if isinstance(exc, json.JSONDecodeError):
        return "Unexpected response from server (not JSON).", f"The API Base URL may point to the wrong endpoint.\nBase URL: {base_url}\nDetail: {exc}"

    if isinstance(exc, UnicodeEncodeError):
        return "Invalid character in API Key or Base URL.", (
            "Your API Key or Base URL contains non-ASCII characters (e.g., Chinese, emoji). "
            "Please use only ASCII characters in Settings → AI."
        )

    if isinstance(exc, ValueError):
        return str(exc), ""

    return f"Unexpected error: {type(exc).__name__}", str(exc)


# Public API.

class AIWorker:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        messages: list[dict],
        on_done: Callable[[str], None],
        on_error: Callable[[str, str], None],
        max_tokens: int = 2048,
        on_status: Optional[Callable[[str], None]] = None,
    ):
        # Keep the invoker alive for the lifetime of the worker thread.
        self.invoker = _CallbackInvoker(on_done, on_error, on_status)
        self._cancelled = threading.Event()
        self.thread = threading.Thread(
            target=self._run,
            args=(api_key, base_url, model, messages, max_tokens),
            daemon=True,
        )
        self.thread.start()

    def cancel(self) -> None:
        """Stop delivering callbacks to a dialog that has been closed."""
        self._cancelled.set()
        self.invoker.detach_callbacks()

    def _run(self, api_key, base_url, model, messages, max_tokens):
        invoker = self.invoker

        def _status_key(key: str, **kwargs):
            if self._cancelled.is_set():
                return
            try:
                invoker.status_signal.emit(json.dumps({"key": key, **kwargs}))
            except Exception:
                pass

        try:
            if self._cancelled.is_set():
                return
            _status_key("ai_status_start")
            url, is_anthropic = _resolve_endpoint(base_url)
            _status_key("ai_status_build", model=model)
            req = _build_request(url, is_anthropic, api_key,
                                 model, messages, max_tokens)
            _status_key("ai_status_connect", model=model)
            data = _read_json_with_retries(
                req,
                timeout=60,
                is_cancelled=self._cancelled.is_set,
                on_wait=lambda: _status_key("ai_status_wait"),
            )
            if self._cancelled.is_set():
                return
            _status_key("ai_status_parse")
            text = _extract_text(data, is_anthropic)
            if self._cancelled.is_set():
                return
            _status_key("ai_status_done")
            invoker.done_signal.emit(text)
        except Exception as exc:
            if self._cancelled.is_set():
                return
            short, detail = _classify(exc, api_key, base_url, model)
            _status_key("ai_status_error", raw=short)
            invoker.error_signal.emit(short, detail)

    @staticmethod
    def test(api_key: str, base_url: str, model: str,
             on_done: Callable[[str], None],
             on_error: Callable[[str, str], None],
             on_status: Optional[Callable[[str], None]] = None) -> None:
        """Run a quick connectivity test on a short-lived background thread.

        This uses a short network timeout so the Settings UI recovers quickly
        instead of waiting for the full AI request timeout used in normal runs.
        """
        # Use _CallbackInvoker to marshal callbacks to the Qt main thread.
        invoker = _CallbackInvoker(on_done, on_error, on_status)
        # Retain the invoker until the test completes to avoid it being
        # garbage-collected while background thread runs and signals are used.
        _retain_test_invoker(invoker)
        # Remove invoker when done or error to allow GC.

        def _cleanup_on_done(_text: str):
            _release_test_invoker(invoker)

        def _cleanup_on_err(_short: str, _detail: str):
            _release_test_invoker(invoker)

        invoker.done_signal.connect(_cleanup_on_done)
        invoker.error_signal.connect(_cleanup_on_err)

        # Basic validation: report missing configuration immediately via invoker.
        if not api_key:
            try:
                invoker.error_signal.emit(
                    "ai_err_api_key_missing", "ai_err_api_key_missing_detail")
            except Exception:
                pass
            return
        if not base_url:
            try:
                invoker.error_signal.emit(
                    "ai_err_baseurl_missing", "ai_err_baseurl_missing_detail")
            except Exception:
                pass
            return
        if not model:
            try:
                invoker.error_signal.emit(
                    "ai_err_model_missing", "ai_err_model_missing_detail")
            except Exception:
                pass
            return

        def _run_test():
            def _s_key(key: str, **kwargs):
                try:
                    invoker.status_signal.emit(
                        json.dumps({"key": key, **kwargs}))
                except Exception:
                    pass

            try:
                _s_key("ai_status_start")
                url, is_anthropic = _resolve_endpoint(base_url)
                _s_key("ai_status_build", model=model)
                req = _build_request(url, is_anthropic, api_key, model,
                                     [{"role": "user", "content": "Reply with exactly one word: OK"}],
                                     16)
                # Fast socket check before the HTTP test request.
                parsed = urllib.parse.urlparse(base_url)
                host = parsed.hostname
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                try:
                    _s_key("ai_status_connect", model=model)
                    conn = socket.create_connection((host, port), timeout=4)
                    conn.close()
                except Exception as sock_exc:
                    raise urllib.error.URLError(
                        f"Network connect failed: {sock_exc}") from sock_exc

                # Keep test latency low with a short request timeout.
                with urllib.request.urlopen(req, timeout=8) as resp:
                    _s_key("ai_status_wait")
                    buf = _read_limited_response(resp)
                    data = json.loads(buf) if buf else {}
                _s_key("ai_status_parse")
                text = _extract_text(data, is_anthropic)
                _s_key("ai_status_done")
                try:
                    invoker.done_signal.emit(text)
                except Exception:
                    pass
            except Exception as exc:
                short, detail = _classify(exc, api_key, base_url, model)
                _s_key("ai_status_error", raw=short)
                try:
                    invoker.error_signal.emit(short, detail)
                except Exception:
                    pass

        threading.Thread(target=_run_test, daemon=True).start()



# LocalModelWorker with the same callback contract as AIWorker.

class LocalModelWorker:
    """Drop-in replacement for :class:`AIWorker` using on-device inference.

    Shares the same *on_done* / *on_error* / *on_status* callback contract so
    :class:`~ui.dialogs.ai_dialogs.AIProgressDialog` works unchanged.

    Fallback error keys (emitted via *on_error*):
    * ``"local_model_load_fail"``      — OOM / llama.cpp runtime error
    * ``"local_model_not_downloaded"`` — file missing
    * ``"local_model_import_error"``   — llama-cpp-python not installed
    """

    def __init__(
        self,
        messages: list[dict],
        on_done:   Callable[[str], None],
        on_error:  Callable[[str, str], None],
        services=None,
        max_tokens:  int   = 1024,
        temperature: float = 0.3,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.invoker = _CallbackInvoker(on_done, on_error, on_status)
        self._cancelled = threading.Event()
        self.thread  = threading.Thread(
            target=self._run,
            args=(messages, services, max_tokens, temperature),
            daemon=True,
        )
        self.thread.start()

    def cancel(self) -> None:
        """Stop delivering callbacks to a dialog that has been closed."""
        self._cancelled.set()
        self.invoker.detach_callbacks()

    def _run(self, messages, services, max_tokens, temperature):
        invoker = self.invoker

        def _status(key: str) -> None:
            if self._cancelled.is_set():
                return
            try:
                invoker.status_signal.emit(json.dumps({"key": key}))
            except Exception:
                pass

        try:
            if self._cancelled.is_set():
                return
            from services.local_model_service import LocalModelService
            # The dialog already emits "local_model_loading" before worker start.
            svc = LocalModelService.get(services)
            # load_provider() performs lazy loading and may install dependencies.
            svc.load_provider(services=services)
            if self._cancelled.is_set():
                return
            _status("local_model_loaded")
            _status("local_model_generating")
            text = svc.generate(messages, temperature=temperature,
                                max_tokens=max_tokens, services=services)
            if self._cancelled.is_set():
                return
            _status("ai_status_done")
            invoker.done_signal.emit(text)

        except MemoryError as exc:
            if self._cancelled.is_set():
                return
            invoker.error_signal.emit("local_model_load_fail", str(exc))
        except FileNotFoundError as exc:
            if self._cancelled.is_set():
                return
            invoker.error_signal.emit("local_model_not_downloaded", str(exc))
        except ImportError as exc:
            if self._cancelled.is_set():
                return
            invoker.error_signal.emit("local_model_import_error", str(exc))
        except RuntimeError as exc:
            if self._cancelled.is_set():
                return
            if str(exc) == "ai_assist.local_model_not_running":
                invoker.error_signal.emit("ai_assist.local_model_not_running", "")
            else:
                invoker.error_signal.emit("local_model_load_fail", str(exc))
        except Exception as exc:
            if self._cancelled.is_set():
                return
            invoker.error_signal.emit(
                f"Local model error: {type(exc).__name__}", str(exc))
