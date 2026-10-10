"""Short-lived OAuth callback listener bound exclusively to IPv4 loopback."""

import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import time
from urllib.parse import parse_qs, urlsplit

from worklogger.domain.shared.errors import AuthenticationError, CancellationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _


class LoopbackAuthorization:
    def __init__(self, *, state, hostname="127.0.0.1", timeout=180):
        if hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("identity_redirect_invalid")
        self.state, self.timeout = state, timeout
        self.result = None
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(2)
                super().setup()

            def log_message(self, *_args):
                pass

            def do_GET(self):
                accepted = owner._accept(self.path, self.headers.get("Host", ""))
                self.send_response(200 if accepted else 400)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
                self.end_headers()
                text = (_("Authorization response received. Return to WorkLogger to continue.") if accepted
                        else _("This authorization response is invalid. Return to WorkLogger."))
                try:
                    self.wfile.write(text.encode("utf-8"))
                except OSError:
                    pass
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.server.timeout = 0.1
        self.authority = f"{hostname}:{self.server.server_port}"
        self.redirect_uri = f"http://{self.authority}/callback"

    def _accept(self, target, host):
        if self.result is not None or host != self.authority or len(target) > 8192:
            return False
        try:
            parsed = urlsplit(target)
            if parsed.path != "/callback" or parsed.scheme or parsed.netloc or parsed.fragment:
                return False
            values = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=12)
            if any(len(value) != 1 for value in values.values()):
                return False
            state = values.get("state", [""])[0]
            if not state or not hmac.compare_digest(state.encode(), self.state.encode()):
                return False
            code, error = values.get("code", [""])[0], values.get("error", [""])[0]
            if bool(code) == bool(error):
                return False
            if error:
                cls = CancellationError if error == "access_denied" else AuthenticationError
                name = "identity_authorization_cancelled" if error == "access_denied" else "identity_auth_failed"
                self.result = Result.failure(cls(name, name))
            else:
                self.result = Result.success(code)
            return True
        except (ValueError, UnicodeError):
            return False

    def wait(self, cancellation):
        deadline = time.monotonic() + self.timeout
        while self.result is None:
            if cancellation is not None and cancellation.is_cancelled():
                return Result.failure(CancellationError("identity_authorization_cancelled", "identity_authorization_cancelled"))
            if time.monotonic() >= deadline:
                return Result.failure(AuthenticationError("identity_authorization_timeout", "identity_authorization_timeout"))
            self.server.handle_request()
        return self.result

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.server.server_close()
