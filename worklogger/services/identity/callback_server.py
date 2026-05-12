from __future__ import annotations

import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .errors import IdentityCallbackTimeout


class LoopbackCallbackServer:
    def __init__(self, *, timeout_seconds: int = 120):
        self._timeout_seconds = timeout_seconds
        self._queue: queue.Queue[dict[str, str]] = queue.Queue(maxsize=1)
        callback_queue = self._queue

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format, *args):
                return

            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                values = {
                    key: vals[0]
                    for key, vals in parse_qs(parsed.query, keep_blank_values=True).items()
                    if vals
                }
                try:
                    callback_queue.put_nowait(values)
                except queue.Full:
                    pass
                body = (
                    b"<!doctype html><html><head><meta charset='utf-8'>"
                    b"<title>WorkLogger</title></head><body>"
                    b"<h1>Sign-in received</h1>"
                    b"<p>You can close this browser tab and return to WorkLogger.</p>"
                    b"</body></html>"
                )
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/callback"

    def wait_for_callback(self) -> dict[str, str]:
        try:
            return self._queue.get(timeout=self._timeout_seconds)
        except queue.Empty as exc:
            raise IdentityCallbackTimeout("identity_callback_timeout") from exc

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
