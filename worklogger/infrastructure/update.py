"""Update-check infrastructure adapter."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request
from worklogger.infrastructure.http import https_opener

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class GitHubReleaseUpdateChecker:
    def __init__(
        self,
        *,
        api_url: str,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 64 * 1024,
        opener=None,
    ) -> None:
        self._api_url = api_url
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._opener = opener or https_opener(public_only=True)

    def check_latest_version(self, current_version: str) -> Result[str | None]:
        try:
            request = Request(
                self._api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "WorkLogger",
                },
            )
            with self._opener(request, timeout=self._timeout_seconds) as response:
                payload = response.read(self._max_response_bytes + 1)
            if len(payload) > self._max_response_bytes:
                raise ValueError("update_response_too_large")
            data = json.loads(payload.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("update_response_invalid")
            if data.get("draft") or data.get("prerelease"):
                return Result.success(None)
            latest = _normalize_version(str(data.get("tag_name") or data.get("name") or ""))
            current = _normalize_version(current_version)
            if "-" in latest.split("+", 1)[0]:
                return Result.success(None)
            if latest and _version_tuple(latest) > _version_tuple(current):
                return Result.success(latest)
            return Result.success(None)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            if isinstance(exc, HTTPError):
                exc.close()
            return Result.failure(
                InfrastructureError(
                    "update_check_failed",
                    "update_check_failed",
                    {"error_type": type(exc).__name__},
                )
            )


def _normalize_version(value: str) -> str:
    match = re.fullmatch(
        r"[vV]?((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
        r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?)",
        str(value or "").strip(),
        flags=re.ASCII,
    )
    if not match:
        raise ValueError("update_response_invalid")
    normalized = match.group(1)
    core = normalized.split("+", 1)[0]
    if "-" in core and any(part.isdecimal() and len(part) > 1 and part.startswith("0") for part in core.split("-", 1)[1].split(".")):
        raise ValueError("update_response_invalid")
    return normalized


def _version_tuple(value: str) -> tuple:
    core, separator, pre = _normalize_version(value).split("+", 1)[0].partition("-")
    identifiers = tuple((0, int(part)) if part.isdecimal() else (1, part) for part in pre.split(".")) if separator else ()
    return (*map(int, core.split(".")), not separator, identifiers)

