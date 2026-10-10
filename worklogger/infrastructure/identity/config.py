"""Identity provider configuration helpers."""

from __future__ import annotations

import json
import os
import portalocker
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass, field
from threading import RLock
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.domain.identity.models import normalize_provider
from worklogger.infrastructure.files import atomic_destination
from worklogger.infrastructure.security.key_store import HmacSecretBox
from worklogger.infrastructure.security.paths import credential_directory
from worklogger.infrastructure.identity.oidc import microsoft_oidc_config


@dataclass(frozen=True)
class ProviderRegistration:
    client_id: str = ""
    tenant_id: str = ""
    client_secret: str = field(default="", repr=False)


class IdentityConfigurationStore:
    """Installation-scoped registrations, with managed overrides and encrypted local storage."""

    def __init__(self, path: Path | None = None, *, secret_box=None):
        self._path = path or credential_directory() / "identity-config.enc"
        self._box = secret_box or HmacSecretBox()
        self._lock = RLock()

    def _local(self):
        if not self._path.exists():
            return {}
        if self._path.stat().st_size > 65536:
            raise ValueError("identity_configuration_invalid")
        data = json.loads(self._box.decrypt(self._path.read_text(encoding="utf-8")))
        if not isinstance(data, dict):
            raise ValueError("identity_configuration_invalid")
        return data

    def managed(self, provider):
        keys = (f"{provider}_client_id", f"{provider}_login_enabled",
                "google_client_secret" if provider == "google" else "microsoft_tenant_id")
        external = _file_config()
        return any(key in external or os.environ.get("WORKLOGGER_" + key.upper(), "").strip() for key in keys)

    def load(self, provider):
        try:
            provider = normalize_provider(provider)
            with self._lock:
                values = self._local()
            if self.managed(provider):
                for key in (f"{provider}_client_id", f"{provider}_login_enabled",
                            "google_client_secret" if provider == "google" else "microsoft_tenant_id"):
                    values.pop(key, None)
            values.update(_file_config())
            def value(key, default=""):
                return str(os.environ.get("WORKLOGGER_" + key.upper(), "").strip() or values.get(key, default) or "").strip()
            registration = ProviderRegistration(value(f"{provider}_client_id"),
                value("microsoft_tenant_id") if provider == "microsoft" else "",
                value("google_client_secret") if provider == "google" else "")
            _validate_registration(provider, registration)
            enabled = _bool(value("identity_enabled", "1"), True) and _bool(value(f"{provider}_login_enabled", "1"), True)
            return Result.success((registration, enabled))
        except Exception:
            return Result.failure(ValidationError("identity_configuration_invalid", "identity_configuration_invalid"))

    def save(self, provider, registration):
        try:
            provider = normalize_provider(provider)
            _validate_registration(provider, registration)
            if self.managed(provider):
                return Result.failure(ValidationError("identity_configuration_managed", "identity_configuration_managed"))
            self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with self._lock, portalocker.Lock(str(self._path) + ".lock", timeout=5):
                values = self._local()
                values[f"{provider}_client_id"] = registration.client_id.strip()
                values[f"{provider}_login_enabled"] = "1"
                if provider == "google":
                    values["google_client_secret"] = registration.client_secret.strip()
                else:
                    values["microsoft_tenant_id"] = registration.tenant_id.strip()
                stored = self._box.encrypt(json.dumps(values))
                with atomic_destination(self._path) as temporary:
                    temporary.write_text(stored, encoding="utf-8")
            return Result.success(None)
        except ValueError:
            return Result.failure(ValidationError("identity_configuration_invalid", "identity_configuration_invalid"))
        except Exception:
            return Result.failure(InfrastructureError("identity_configuration_save_failed", "identity_configuration_save_failed"))


def _validate_registration(provider, registration):
    for value in (registration.client_id, registration.tenant_id, registration.client_secret):
        if len(value) > 1024 or any(ord(char) < 33 or ord(char) > 126 for char in value.strip()):
            raise ValueError("identity_configuration_invalid")
    if provider == "microsoft" and registration.client_id:
        microsoft_oidc_config(registration.client_id, registration.tenant_id)


def identity_enabled() -> bool:
    return _bool(_value("identity_enabled", "WORKLOGGER_IDENTITY_ENABLED", "1"), True)


def provider_configured(provider: str) -> bool:
    loaded = IdentityConfigurationStore().load(provider)
    return bool(loaded.ok and loaded.value[0].client_id)


def provider_available(provider: str) -> bool:
    loaded = IdentityConfigurationStore().load(provider)
    return bool(loaded.ok and loaded.value[0].client_id and loaded.value[1])


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
        resolved = Path(path).expanduser().resolve()
        stat = resolved.stat()
        if stat.st_size > 65536:
            return {}
        data = _read_config(str(resolved), stat.st_mtime_ns, stat.st_size)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=8)
def _read_config(path: str, modified: int, size: int) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _bool(value: str, default: bool) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "disabled"}
