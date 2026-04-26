"""Remember-session storage for this machine.

The preferred backend is the OS credential store exposed by ``keyring``. If it
is unavailable, the module falls back to the previous Fernet-encrypted local
file so remember-me keeps working in restricted environments.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from config.constants import (
    APP_ID,
    REMEMBER_ACTIVE_USER_KEY,
    REMEMBER_FALLBACK_FILENAME,
    REMEMBER_FILE_PREFIX_V1,
    REMEMBER_FILE_PREFIX_V2,
    REMEMBER_SERVICE_NAME,
    REMEMBER_STORE_FERNET_FILE,
    REMEMBER_STORE_KEYRING,
    REMEMBER_TOKEN_KEY,
)
from data.db import DB_PATH
from utils.crypto import machine_key

_log = logging.getLogger(__name__)

MISSING_CRYPTOGRAPHY_MESSAGE = (
    "Remember-token encryption requires the 'cryptography' package. "
    "Please install it via pip install cryptography."
)


@dataclass(frozen=True)
class RememberSession:
    username: str
    token: str
    backend: str


def _token_path() -> Path:
    return Path(DB_PATH).with_name(REMEMBER_FALLBACK_FILENAME)


def _fernet():
    try:
        from cryptography.fernet import Fernet

        return Fernet(base64.urlsafe_b64encode(machine_key()))
    except Exception as exc:
        _log.warning("Fernet unavailable for remember token storage: %s", exc)
        return None


def _keyring_get(account: str) -> Optional[str]:
    try:
        import keyring

        return keyring.get_password(REMEMBER_SERVICE_NAME, account)
    except Exception as exc:
        _log.info("Keyring remember-token read failed for %s: %s", account, exc)
        return None


def _keyring_set(account: str, value: str) -> bool:
    try:
        import keyring

        keyring.set_password(REMEMBER_SERVICE_NAME, account, value)
        return True
    except Exception as exc:
        _log.info("Keyring remember-token write failed for %s: %s", account, exc)
        return False


def _keyring_delete(account: str) -> None:
    try:
        import keyring

        keyring.delete_password(REMEMBER_SERVICE_NAME, account)
    except Exception as exc:
        _log.info("Keyring remember-token delete ignored for %s: %s", account, exc)


def _legacy_keyring_get() -> Optional[str]:
    try:
        import keyring

        return keyring.get_password(APP_ID, REMEMBER_TOKEN_KEY)
    except Exception:
        return None


def _legacy_keyring_delete() -> None:
    try:
        import keyring

        keyring.delete_password(APP_ID, REMEMBER_TOKEN_KEY)
    except Exception:
        pass


def _decrypt_file_payload(raw: str) -> Optional[str]:
    fernet = _fernet()
    if not fernet:
        return None
    try:
        return fernet.decrypt(raw.encode("utf-8")).decode("utf-8")
    except Exception as exc:
        _log.warning("Failed to decrypt remember-token file: %s", exc)
        return None


def _read_file_store() -> Tuple[str, Dict[str, str]]:
    path = _token_path()
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "", {}
    if not raw:
        return "", {}

    if raw.startswith(REMEMBER_FILE_PREFIX_V2):
        decrypted = _decrypt_file_payload(raw[len(REMEMBER_FILE_PREFIX_V2):])
        if decrypted is None:
            return "", {}
        try:
            data = json.loads(decrypted)
        except json.JSONDecodeError as exc:
            _log.warning("Invalid remember-token file payload: %s", exc)
            return "", {}
        active = str(data.get("active_username") or "")
        tokens_src = data.get("tokens")
        if not isinstance(tokens_src, dict):
            return "", {}
        tokens = {
            str(username): str(token)
            for username, token in tokens_src.items()
            if username and token
        }
        return active, tokens

    if raw.startswith(REMEMBER_FILE_PREFIX_V1):
        decrypted = _decrypt_file_payload(raw[len(REMEMBER_FILE_PREFIX_V1):])
        if decrypted:
            return "", {"": decrypted}
        return "", {}

    return "", {"": raw}


def _write_file_store(active_username: str, tokens: Dict[str, str]) -> None:
    path = _token_path()
    tokens = {
        str(username): str(token)
        for username, token in tokens.items()
        if username and token
    }
    if not tokens:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("Failed to remove remember-token file: %s", exc)
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log.warning("Failed to create remember-token directory: %s", exc)
        raise
    fernet = _fernet()
    if not fernet:
        raise ImportError(MISSING_CRYPTOGRAPHY_MESSAGE)
    payload = json.dumps(
        {"active_username": active_username, "tokens": tokens},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    encrypted = fernet.encrypt(payload.encode("utf-8")).decode("utf-8")
    try:
        path.write_text(REMEMBER_FILE_PREFIX_V2 + encrypted, encoding="utf-8")
    except OSError as exc:
        _log.warning("Failed to write remember-token file: %s", exc)
        raise


def _safe_write_file_store(active_username: str, tokens: Dict[str, str]) -> None:
    try:
        _write_file_store(active_username, tokens)
    except Exception as exc:
        _log.warning("Failed to update remember-token fallback file: %s", exc)
        try:
            _token_path().unlink(missing_ok=True)
        except OSError as unlink_exc:
            _log.warning("Failed to remove remember-token fallback file: %s", unlink_exc)


def _save_to_file(username: str, token: str) -> None:
    active, tokens = _read_file_store()
    tokens[username] = token
    _write_file_store(username or active, tokens)


def _save_to_keyring(username: str, token: str) -> bool:
    if not _keyring_set(username, token):
        return False
    if _keyring_set(REMEMBER_ACTIVE_USER_KEY, username):
        return True
    _keyring_delete(username)
    return False


def _cleanup_file_after_keyring_save(username: str) -> None:
    _active, tokens = _read_file_store()
    if not tokens:
        try:
            _token_path().unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("Failed to remove legacy remember-token file: %s", exc)
        return

    remaining = {
        stored_username: stored_token
        for stored_username, stored_token in tokens.items()
        if stored_username != username
    }
    migrated = all(
        _keyring_set(stored_username, stored_token)
        for stored_username, stored_token in remaining.items()
    )
    if not migrated:
        return

    try:
        _token_path().unlink(missing_ok=True)
    except OSError as exc:
        _log.warning("Failed to remove legacy remember-token file: %s", exc)


def _load_from_file() -> Optional[RememberSession]:
    active, tokens = _read_file_store()
    if active and tokens.get(active):
        return RememberSession(active, tokens[active], REMEMBER_STORE_FERNET_FILE)
    if "" in tokens:
        return RememberSession("", tokens[""], REMEMBER_STORE_FERNET_FILE)
    return None


def load_remember_session() -> Optional[RememberSession]:
    active_username = _keyring_get(REMEMBER_ACTIVE_USER_KEY)
    if active_username:
        token = _keyring_get(active_username)
        if token:
            return RememberSession(active_username, token, REMEMBER_STORE_KEYRING)
        _keyring_delete(REMEMBER_ACTIVE_USER_KEY)

    legacy_token = _legacy_keyring_get()
    if legacy_token:
        return RememberSession("", legacy_token, REMEMBER_STORE_KEYRING)

    return _load_from_file()


def load_remember_token() -> str:
    session = load_remember_session()
    return session.token if session else ""


def save_remember_token(username: str, token: str) -> None:
    username = username.strip()
    if not username:
        raise ValueError("username_required")
    if not token:
        clear_remember_token(username)
        return

    if _save_to_keyring(username, token):
        _legacy_keyring_delete()
        _cleanup_file_after_keyring_save(username)
        return

    _save_to_file(username, token)


def clear_active_remember_user() -> None:
    _keyring_delete(REMEMBER_ACTIVE_USER_KEY)
    active, tokens = _read_file_store()
    if tokens:
        _safe_write_file_store("", tokens)
    else:
        try:
            _token_path().unlink(missing_ok=True)
        except OSError as exc:
            _log.warning("Failed to remove remember-token file: %s", exc)


def clear_remember_token(username: Optional[str] = None) -> None:
    username = username.strip() if username else ""
    if username:
        _keyring_delete(username)
        if _keyring_get(REMEMBER_ACTIVE_USER_KEY) == username:
            _keyring_delete(REMEMBER_ACTIVE_USER_KEY)
        active, tokens = _read_file_store()
        if username in tokens:
            tokens.pop(username, None)
            _safe_write_file_store("" if active == username else active, tokens)
        return

    _keyring_delete(REMEMBER_ACTIVE_USER_KEY)
    _legacy_keyring_delete()
    try:
        _token_path().unlink(missing_ok=True)
    except OSError as exc:
        _log.warning("Failed to remove remember-token file: %s", exc)
