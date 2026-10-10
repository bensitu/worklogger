"""Account-scoped HTTP CONNECT proxy configuration for HTTPS adapters."""

from urllib.parse import quote, urlparse

from worklogger.config.constants import (
    NETWORK_PROXY_ADDRESS_SETTING_KEY, NETWORK_PROXY_PORT_SETTING_KEY,
    NETWORK_PROXY_ENABLED_SETTING_KEY, NETWORK_PROXY_USERNAME_SETTING_KEY,
    NETWORK_PROXY_DOMAIN_SETTING_KEY,
)
from worklogger.infrastructure.http import https_opener


class AccountHTTPTransport:
    def __init__(self, *, settings, user_id, proxy_password, opener_factory=https_opener):
        self._settings = settings
        self._user_id = user_id
        self._proxy_password = proxy_password
        self._opener_factory = opener_factory

    def opener(self, *, public_only=False, allow_redirects=True):
        def open_request(request, *, timeout):
            proxy = self._proxy_url()
            return self._opener_factory(public_only=public_only, allow_redirects=allow_redirects,
                                       proxy_url=proxy)(request, timeout=timeout)
        return open_request

    def _proxy_url(self):
        values = self._settings.get_all(self._user_id)
        if values.get(NETWORK_PROXY_ENABLED_SETTING_KEY, "0") != "1":
            return None
        address = str(values.get(NETWORK_PROXY_ADDRESS_SETTING_KEY) or "").strip()
        port = int(values.get(NETWORK_PROXY_PORT_SETTING_KEY) or "0")
        if not address or not 1 <= port <= 65535 or any(ord(char) < 32 for char in address):
            raise ValueError("proxy_configuration_invalid")
        parsed = urlparse(address if "://" in address else "http://" + address)
        if (parsed.scheme != "http" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or (parsed.port is not None and parsed.port != port)):
            raise ValueError("proxy_configuration_invalid")
        host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
        username = str(values.get(NETWORK_PROXY_USERNAME_SETTING_KEY) or "").strip()
        domain = str(values.get(NETWORK_PROXY_DOMAIN_SETTING_KEY) or "").strip()
        if any(ord(char) < 32 for char in username + domain) or ":" in username:
            raise ValueError("proxy_configuration_invalid")
        authentication = ""
        if username:
            password = self._proxy_password.load()
            if not password.ok:
                raise ValueError("credential_storage_unavailable")
            username = domain + "\\" + username if domain else username
            authentication = quote(username, safe="") + ":" + quote(password.value or "", safe="") + "@"
        return f"http://{authentication}{host}:{port}"
