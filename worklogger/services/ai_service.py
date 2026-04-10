"""AI API integration — OpenAI-compatible + Anthropic, stdlib only."""

from __future__ import annotations
import json
import threading
import socket
import urllib.parse
import time
import urllib.request
import urllib.error
import traceback
import os
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Helper to safely invoke callbacks on main thread
# ---------------------------------------------------------------------------


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

    def _on_done(self, text):
        self.on_done(text)

    def _on_error(self, short, detail):
        self.on_error(short, detail)

    def _on_status(self, msg):
        if self.on_status:
            self.on_status(msg)


# Keep references to short-lived test invokers so they are not garbage-collected
# while the background test thread is running. Entries are removed on done/error.
_test_invokers: list[_CallbackInvoker] = []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sanitize_header(value: str) -> str:
    return ''.join(c for c in value if 32 <= ord(c) <= 126)


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
        body = exc.read().decode("utf-8", errors="replace")
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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

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
        # Store invoker as instance variable to prevent garbage collection
        self.invoker = _CallbackInvoker(on_done, on_error, on_status)
        self.thread = threading.Thread(
            target=self._run,
            args=(api_key, base_url, model, messages, max_tokens),
            daemon=True,
        )
        self.thread.start()

    def _run(self, api_key, base_url, model, messages, max_tokens):
        invoker = self.invoker  # local reference

        def _status_key(key: str, **kwargs):
            try:
                invoker.status_signal.emit(json.dumps({"key": key, **kwargs}))
            except Exception:
                pass

        try:
            _status_key("ai_status_start")
            url, is_anthropic = _resolve_endpoint(base_url)
            _status_key("ai_status_build", model=model)
            req = _build_request(url, is_anthropic, api_key,
                                 model, messages, max_tokens)
            _status_key("ai_status_connect", model=model)
            with urllib.request.urlopen(req, timeout=60) as resp:
                _status_key("ai_status_wait")
                data = json.loads(resp.read())
            _status_key("ai_status_parse")
            text = _extract_text(data, is_anthropic)
            _status_key("ai_status_done")
            invoker.done_signal.emit(text)
        except Exception as exc:
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
        _test_invokers.append(invoker)
        # Remove invoker when done or error to allow GC.

        def _cleanup_on_done(_text: str):
            try:
                if invoker in _test_invokers:
                    _test_invokers.remove(invoker)
            except Exception:
                pass

        def _cleanup_on_err(_short: str, _detail: str):
            try:
                if invoker in _test_invokers:
                    _test_invokers.remove(invoker)
            except Exception:
                pass

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
                # quick host resolve/connect
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

                # Short POST and read
                with urllib.request.urlopen(req, timeout=8) as resp:
                    _s_key("ai_status_wait")
                    buf = resp.read()
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
