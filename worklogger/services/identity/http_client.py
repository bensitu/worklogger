from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Type

from .errors import IdentityBrokerError, IdentityError, IdentityTokenExchangeFailed

MAX_RESPONSE_BYTES = 1024 * 1024
USER_AGENT = "WorkLogger/3.2"


def post_form(
    url: str,
    data: dict[str, str],
    *,
    timeout: float = 15,
    error_cls: Type[IdentityError] = IdentityTokenExchangeFailed,
) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    return _request_json(
        urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
        ),
        timeout=timeout,
        error_cls=error_cls,
    )


def post_json(
    url: str,
    data: dict,
    *,
    timeout: float = 15,
    error_cls: Type[IdentityError] = IdentityBrokerError,
) -> dict:
    body = json.dumps(data).encode("utf-8")
    return _request_json(
        urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        ),
        timeout=timeout,
        error_cls=error_cls,
    )


def get_json(
    url: str,
    *,
    timeout: float = 15,
    error_cls: Type[IdentityError] = IdentityTokenExchangeFailed,
) -> dict:
    return _request_json(
        urllib.request.Request(url, headers={"User-Agent": USER_AGENT}),
        timeout=timeout,
        error_cls=error_cls,
    )


def _request_json(
    request: urllib.request.Request,
    *,
    timeout: float,
    error_cls: Type[IdentityError],
) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = _read_limited(response)
    except urllib.error.HTTPError as exc:
        detail = _safe_error_detail(exc)
        raise error_cls(detail or f"identity_http_{exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise error_cls("identity_network_error") from exc
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except json.JSONDecodeError as exc:
        raise error_cls("identity_invalid_json") from exc


def _read_limited(response) -> bytes:
    body = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise IdentityTokenExchangeFailed("identity_response_too_large")
    return body


def _safe_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            return f"identity_http_{exc.code}"
        data = json.loads(body.decode("utf-8", errors="replace") or "{}")
        error = data.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or f"identity_http_{exc.code}")
        if isinstance(error, str):
            return error
        return str(data.get("message") or f"identity_http_{exc.code}")
    except Exception:
        return f"identity_http_{exc.code}"
