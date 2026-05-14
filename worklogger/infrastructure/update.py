"""Update-check infrastructure adapter."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result


class GitHubReleaseUpdateChecker:
    def __init__(
        self,
        *,
        api_url: str,
        timeout_seconds: float = 5.0,
        max_response_bytes: int = 64 * 1024,
    ) -> None:
        self._api_url = api_url
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes

    def check_latest_version(self, current_version: str) -> Result[str | None]:
        try:
            request = Request(
                self._api_url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "WorkLogger",
                },
            )
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = response.read(self._max_response_bytes + 1)
            if len(payload) > self._max_response_bytes:
                raise ValueError("update_response_too_large")
            data = json.loads(payload.decode("utf-8"))
            latest = _normalize_version(str(data.get("tag_name") or data.get("name") or ""))
            current = _normalize_version(current_version)
            if latest and _version_tuple(latest) > _version_tuple(current):
                return Result.success(latest)
            return Result.success(None)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return Result.failure(
                InfrastructureError(
                    "update_check_failed",
                    "update_check_failed",
                    {"reason": str(exc)},
                )
            )


class DisabledUpdateChecker:
    def check_latest_version(self, current_version: str) -> Result[str | None]:
        del current_version
        return Result.success(None)


def _normalize_version(value: str) -> str:
    match = re.search(r"(\d+(?:\.\d+){0,3})", str(value or ""))
    return match.group(1) if match else "0"


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in _normalize_version(value).split(".")]
    return tuple(parts + [0] * (4 - len(parts)))

