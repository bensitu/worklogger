"""Remember-login session store."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from worklogger.config.constants import REMEMBER_SESSION_FILENAME

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.security.key_store import HmacSecretBox
from worklogger.infrastructure.files import atomic_destination

REMEMBER_TOKEN_SECRET_NAME = "remember_login_token"


class SecretStore(Protocol):
    def get_secret(self, name: str) -> Result[str | None]:
        ...

    def set_secret(self, name: str, value: str) -> Result[None]:
        ...


class RememberTokenSessionStore:
    def __init__(
        self,
        secret_store: SecretStore,
        *,
        secret_name: str = REMEMBER_TOKEN_SECRET_NAME,
    ) -> None:
        self._secret_store = secret_store
        self._secret_name = secret_name

    def load_token(self) -> Result[str | None]:
        return self._secret_store.get_secret(self._secret_name)

    def save_token(self, token: str) -> Result[None]:
        return self._secret_store.set_secret(self._secret_name, token)

    def clear_token(self) -> Result[None]:
        return self._secret_store.set_secret(self._secret_name, "")


class FileRememberTokenSessionStore:
    def __init__(
        self,
        path: Path | None = None,
        *,
        secret_box: HmacSecretBox | None = None,
    ) -> None:
        self._path = path or _default_session_path()
        self._secret_box = secret_box or HmacSecretBox()

    def load_token(self) -> Result[str | None]:
        if not self._path.exists():
            return Result.success(None)
        try:
            stored = self._path.read_text(encoding="utf-8").strip()
            if not stored:
                return Result.success(None)
            token = self._secret_box.decrypt(stored)
            if stored.startswith("enc1:"):
                upgraded = self.save_token(token)
                if not upgraded.ok:
                    return Result.failure(upgraded.error)
            return Result.success(token)
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "remember_session_load_failed",
                    "remember_session_load_failed",
                    {"reason": str(exc)},
                )
            )

    def save_token(self, token: str) -> Result[None]:
        try:
            if not token:
                return self.clear_token()
            encrypted = self._secret_box.encrypt(token)
            with atomic_destination(self._path) as temporary:
                temporary.write_text(encrypted, encoding="utf-8")
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "remember_session_save_failed",
                    "remember_session_save_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(None)

    def clear_token(self) -> Result[None]:
        try:
            self._path.unlink()
        except FileNotFoundError:
            return Result.success(None)
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "remember_session_clear_failed",
                    "remember_session_clear_failed",
                    {"reason": str(exc)},
                )
            )
        return Result.success(None)


def _default_session_path() -> Path:
    from worklogger.infrastructure.security.paths import credential_directory
    base = credential_directory()
    return base / REMEMBER_SESSION_FILENAME
