from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoogleOAuthConfig:
    client_id: str
    authorization_endpoint: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint: str = "https://oauth2.googleapis.com/token"
    issuer: str = "https://accounts.google.com"
    jwks_uri: str = "https://www.googleapis.com/oauth2/v3/certs"
    scopes: str = "openid email profile"


@dataclass(frozen=True)
class FirebaseBrokerConfig:
    api_key: str
    auth_domain: str = ""
    project_id: str = ""


def normalize_provider(provider: str) -> str:
    provider = str(provider or "").strip().lower()
    if provider not in {"google", "microsoft"}:
        raise ValueError("unsupported_identity_provider")
    return provider


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name)
    if raw == "":
        return default
    return _coerce_bool(raw, default)


def _coerce_bool(value, default: bool) -> bool:
    raw = str(value or "").strip()
    if raw == "":
        return default
    return raw.lower() not in {"0", "false", "no", "off", "disabled"}


def _setting(services, key: str, default: str = "") -> str:
    if services is None:
        return default
    try:
        value = services.get_setting(key, default)
    except Exception:
        return default
    return str(value or default).strip()


def _app_config_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config"
    return Path(__file__).resolve().parents[2] / "config"


def _user_config_dir() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "WorkLogger"
    return Path.home() / ".config" / "worklogger"


def identity_config_paths() -> list[Path]:
    """Return local identity config paths in precedence order."""
    paths: list[Path] = []
    env_path = _env("WORKLOGGER_IDENTITY_CONFIG")
    if env_path:
        paths.append(Path(env_path).expanduser())
    paths.append(_user_config_dir() / "identity.local.json")
    paths.append(_app_config_dir() / "identity.local.json")
    return paths


def _load_file_config() -> dict:
    for path in identity_config_paths():
        try:
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _lookup_path(data: dict, keys: tuple[str, ...]):
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _coerce_str(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value).strip()


def _file_value(key: str, default: str = "") -> str:
    data = _load_file_config()
    if not data:
        return default
    if key in data:
        return _coerce_str(data.get(key), default)
    aliases = {
        "identity_enabled": (
            ("identity", "enabled"),
        ),
        "google_login_enabled": (
            ("google", "enabled"),
        ),
        "microsoft_login_enabled": (
            ("microsoft", "enabled"),
        ),
        "google_client_id": (
            ("google", "client_id"),
            ("google", "clientId"),
            ("googleClientId",),
        ),
        "firebase_api_key": (
            ("firebase", "api_key"),
            ("firebase", "apiKey"),
            ("firebaseApiKey",),
        ),
        "firebase_auth_domain": (
            ("firebase", "auth_domain"),
            ("firebase", "authDomain"),
            ("firebaseAuthDomain",),
        ),
        "firebase_project_id": (
            ("firebase", "project_id"),
            ("firebase", "projectId"),
            ("firebaseProjectId",),
        ),
    }
    for path in aliases.get(key, ()):
        value = _lookup_path(data, path)
        if value is not None:
            return _coerce_str(value, default)
    return default


def _config_value(services, setting_key: str, env_name: str, default: str = "") -> str:
    return _env(env_name) or _file_value(setting_key) or _setting(services, setting_key, default)


def _config_bool(services, setting_key: str, env_name: str, default: bool) -> bool:
    raw = _env(env_name)
    if raw:
        return _env_bool(env_name, default)
    file_raw = _file_value(setting_key)
    if file_raw:
        return _coerce_bool(file_raw, default)
    value = _setting(services, setting_key, "1" if default else "0")
    return _coerce_bool(value, default)


def identity_enabled(services=None) -> bool:
    return _config_bool(
        services,
        "identity_enabled",
        "WORKLOGGER_IDENTITY_ENABLED",
        True,
    )


def google_enabled(services=None) -> bool:
    return _config_bool(
        services,
        "google_login_enabled",
        "WORKLOGGER_GOOGLE_LOGIN_ENABLED",
        True,
    )


def microsoft_enabled(services=None) -> bool:
    return _config_bool(
        services,
        "microsoft_login_enabled",
        "WORKLOGGER_MICROSOFT_LOGIN_ENABLED",
        False,
    )


def google_oauth_config(services=None) -> GoogleOAuthConfig | None:
    client_id = _config_value(
        services,
        "google_client_id",
        "WORKLOGGER_GOOGLE_CLIENT_ID",
    )
    if not client_id:
        return None
    return GoogleOAuthConfig(client_id=client_id)


def firebase_broker_config(services=None) -> FirebaseBrokerConfig | None:
    api_key = _config_value(
        services,
        "firebase_api_key",
        "WORKLOGGER_FIREBASE_API_KEY",
    )
    if not api_key:
        return None
    return FirebaseBrokerConfig(
        api_key=api_key,
        auth_domain=_config_value(
            services,
            "firebase_auth_domain",
            "WORKLOGGER_FIREBASE_AUTH_DOMAIN",
        ),
        project_id=_config_value(
            services,
            "firebase_project_id",
            "WORKLOGGER_FIREBASE_PROJECT_ID",
        ),
    )


def provider_configured(provider: str, services=None) -> bool:
    provider = normalize_provider(provider)
    if provider == "google":
        return google_oauth_config(services) is not None and firebase_broker_config(services) is not None
    return False


def provider_available(provider: str, services=None) -> bool:
    provider = normalize_provider(provider)
    if not identity_enabled(services):
        return False
    if provider == "google":
        return google_enabled(services) and provider_configured(provider, services)
    return False
