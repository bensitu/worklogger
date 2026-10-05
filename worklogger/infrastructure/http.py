"""HTTPS transport with explicit certificate and redirect policies."""

import http.client
import ipaddress
import re
import ssl
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, build_opener

import certifi


def validate_https_url(url: str, *, public_only: bool = False) -> str:
    raw = str(url).strip()
    parsed = urlparse(raw)
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or any(ord(char) < 32 for char in raw)):
        raise ValueError("https_url_invalid")
    parsed.port
    if public_only:
        host = parsed.hostname.lower().rstrip(".")
        if host == "localhost" or host.endswith(".localhost"):
            raise ValueError("https_url_invalid")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if re.fullmatch(r"(?:0x[0-9a-f]+|[0-9.]+)", host):
                raise ValueError("https_url_invalid")
        else:
            if not address.is_global:
                raise ValueError("https_url_invalid")
    return raw


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        if self.sock is None or not ipaddress.ip_address(self.sock.getpeername()[0]).is_global:
            self.close()
            raise OSError("http_address_not_public")


class _PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(_PublicHTTPSConnection, request, context=self._context)


class _ValidatedRedirect(HTTPRedirectHandler):
    def __init__(self, *, allow: bool, public_only: bool):
        self._allow = allow
        self._public_only = public_only

    def redirect_request(self, request, response, code, message, headers, new_url):
        if not self._allow:
            raise HTTPError(request.full_url, code, "http_redirect_rejected", headers, response)
        validate_https_url(new_url, public_only=self._public_only)
        return super().redirect_request(request, response, code, message, headers, new_url)


def https_opener(*, public_only: bool = False, allow_redirects: bool = True):
    context = ssl.create_default_context(cafile=certifi.where())
    handler = _PublicHTTPSHandler(context=context) if public_only else HTTPSHandler(context=context)
    opener = build_opener(ProxyHandler({}), handler, _ValidatedRedirect(allow=allow_redirects, public_only=public_only))

    def open_request(request, *, timeout):
        validate_https_url(request.full_url, public_only=public_only)
        return opener.open(request, timeout=timeout)

    return open_request
