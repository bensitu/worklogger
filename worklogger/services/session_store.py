"""Local remember-token storage for the current machine."""

from __future__ import annotations

import base64
import hashlib
import logging
import platform
import uuid
from pathlib import Path

from config.constants import APP_ID, REMEMBER_TOKEN_KEY
from data.db import DB_PATH

_log = logging.getLogger(__name__)
_ENC_PREFIX = "enc1:"


def _token_path() -> Path:
    return Path(DB_PATH).with_name(".worklogger_remember")


def _machine_key() -> bytes:
    seed = f"{platform.node()}|{uuid.getnode()}".encode("utf-8")
    return hashlib.sha256(seed).digest()


def _fernet():
    try:
        from cryptography.fernet import Fernet
        return Fernet(base64.urlsafe_b64encode(_machine_key()))
    except Exception as exc:
        _log.warning("Fernet unavailable for remember token storage: %s", exc)
        return None


def _keyring_get() -> str | None:
    try:
        import keyring
        return keyring.get_password(APP_ID, REMEMBER_TOKEN_KEY)
    except Exception:
        return None


def _keyring_set(token: str) -> bool:
    try:
        import keyring
        keyring.set_password(APP_ID, REMEMBER_TOKEN_KEY, token)
        return True
    except Exception:
        return False


def _keyring_delete() -> None:
    try:
        import keyring
        keyring.delete_password(APP_ID, REMEMBER_TOKEN_KEY)
    except Exception:
        pass


def load_remember_token() -> str:
    token = _keyring_get()
    if token:
        return token
    path = _token_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not raw:
        return ""
    if raw.startswith(_ENC_PREFIX):
        fernet = _fernet()
        if not fernet:
            return ""
        try:
            return fernet.decrypt(raw[len(_ENC_PREFIX):].encode("utf-8")).decode("utf-8")
        except Exception as exc:
            _log.warning("Failed to decrypt remember token: %s", exc)
            return ""
    return raw


def save_remember_token(token: str) -> None:
    if not token:
        clear_remember_token()
        return
    if _keyring_set(token):
        try:
            _token_path().unlink(missing_ok=True)
        except OSError:
            pass
        return

    path = _token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fernet = _fernet()
    if fernet:
        payload = _ENC_PREFIX + fernet.encrypt(token.encode("utf-8")).decode("utf-8")
    else:
        _log.warning("Storing remember token as plain text fallback")
        payload = token
    path.write_text(payload, encoding="utf-8")


def clear_remember_token() -> None:
    _keyring_delete()
    try:
        _token_path().unlink(missing_ok=True)
    except OSError:
        pass
