"""HTTPS transport with explicit certificate and redirect policies."""

import http.client
import ipaddress
import re
import ssl
import socket
import base64
from urllib.error import HTTPError
from urllib.parse import urlparse, unquote
from urllib.request import HTTPSHandler, HTTPRedirectHandler, ProxyHandler, build_opener

import certifi


def validate_https_url(url: str, *, public_only: bool = False) -> str:
    raw = str(url).strip()
    parsed = urlparse(raw)
    if (parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.fragment or any(ord(char) < 32 for char in raw)):
        raise ValueError("https_url_invalid")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("https_url_invalid")
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
        if self._tunnel_host:
            _validate_public_host(self._tunnel_host, self._tunnel_port)
        super().connect()
        if self.sock is None or (not self._tunnel_host and not ipaddress.ip_address(self.sock.getpeername()[0]).is_global):
            self.close()
            raise OSError("http_address_not_public")


def _validate_public_host(host, port):
    validate_https_url(f"https://[{host}]" if ":" in host else f"https://{host}", public_only=True)
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise OSError("http_address_not_public")


class _ExplicitProxyHandler(ProxyHandler):
    def proxy_open(self, request, proxy, _type):
        parsed = urlparse(proxy)
        if parsed.scheme != "http" or not parsed.hostname or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("proxy_configuration_invalid")
        if parsed.username is not None:
            credentials = unquote(parsed.username) + ":" + unquote(parsed.password or "")
            encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
            request.add_header("Proxy-authorization", "Basic " + encoded)
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        request.set_proxy(f"{host}:{parsed.port or 8080}", "http")


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


def https_opener(*, public_only: bool = False, allow_redirects: bool = True, proxy_url: str | None = None):
    context = ssl.create_default_context(cafile=certifi.where())
    handler = _PublicHTTPSHandler(context=context) if public_only else HTTPSHandler(context=context)
    proxy = _ExplicitProxyHandler({"https": proxy_url}) if proxy_url else ProxyHandler({})
    opener = build_opener(proxy, handler, _ValidatedRedirect(allow=allow_redirects, public_only=public_only))

    def open_request(request, *, timeout):
        validate_https_url(request.full_url, public_only=public_only)
        return opener.open(request, timeout=timeout)

    return open_request
