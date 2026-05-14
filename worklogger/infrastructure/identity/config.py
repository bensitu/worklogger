"""Identity provider configuration helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path


def normalize_provider(provider: str) -> str:
    cleaned = str(provider or "").strip().lower()
    if cleaned not in {"google", "microsoft"}:
        raise ValueError("unsupported_identity_provider")
    return cleaned


def identity_enabled() -> bool:
    return _bool(_value("identity_enabled", "WORKLOGGER_IDENTITY_ENABLED", "1"), True)


def provider_configured(provider: str) -> bool:
    provider = normalize_provider(provider)
    if provider == "google":
        return bool(
            _value("google_client_id", "WORKLOGGER_GOOGLE_CLIENT_ID")
            and _value("firebase_api_key", "WORKLOGGER_FIREBASE_API_KEY")
        )
    return False


def provider_available(provider: str) -> bool:
    provider = normalize_provider(provider)
    if not identity_enabled():
        return False
    if provider == "google":
        enabled = _bool(_value("google_login_enabled", "WORKLOGGER_GOOGLE_LOGIN_ENABLED", "1"), True)
        return enabled and provider_configured(provider)
    enabled = _bool(
        _value("microsoft_login_enabled", "WORKLOGGER_MICROSOFT_LOGIN_ENABLED", "0"),
        False,
    )
    return enabled and provider_configured(provider)


def _value(key: str, env_name: str, default: str = "") -> str:
    env = os.environ.get(env_name, "").strip()
    if env:
        return env
    return str(_file_config().get(key, default) or default).strip()


def _file_config() -> dict[str, object]:
    path = os.environ.get("WORKLOGGER_IDENTITY_CONFIG", "").strip()
    if not path:
        return {}
    try:
        data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _bool(value: str, default: bool) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "disabled"}
