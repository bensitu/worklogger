"""Authentication policy helpers."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from collections.abc import Iterable

from worklogger.config.constants import (
    GENERATED_PASSWORD_TOKEN_BYTES,
    LOGIN_FAILURE_LOCK_THRESHOLD,
    LOGIN_LOCKOUT_SCHEDULE,
    LOGIN_LOCKOUT_SECONDS,
    PASSWORD_MIN_LENGTH,
    RECOVERY_KEY_BYTES,
    RECOVERY_KEY_GROUP_SIZE,
    REMEMBER_TOKEN_HASH_PREFIX,
    REMEMBER_TOKEN_LIFETIME_DAYS,
)


def normalize_username(username: str) -> str:
    if not isinstance(username, str):
        raise TypeError("username_must_be_string")
    cleaned = username.strip()
    if not cleaned:
        raise ValueError("username_required")
    return cleaned


def require_password(
    password: str,
    *,
    field_name: str = "password",
    min_length: int = PASSWORD_MIN_LENGTH,
) -> str:
    if not isinstance(password, str):
        raise TypeError(f"{field_name}_must_be_string")
    if not password:
        raise ValueError(f"{field_name}_required")
    if len(password) < int(min_length):
        raise ValueError("password_too_short")
    return password


def generate_initial_password(token_bytes: int = GENERATED_PASSWORD_TOKEN_BYTES) -> str:
    return secrets.token_urlsafe(token_bytes)


def generate_recovery_key(
    *,
    token_bytes: int = RECOVERY_KEY_BYTES,
    group_size: int = RECOVERY_KEY_GROUP_SIZE,
) -> str:
    raw = secrets.token_hex(token_bytes)
    size = max(1, int(group_size))
    return "-".join(raw[index:index + size] for index in range(0, len(raw), size))


def remember_token_storage_value(token: str) -> str:
    if not isinstance(token, str) or not token:
        raise ValueError("remember_token_required")
    return REMEMBER_TOKEN_HASH_PREFIX + hashlib.sha256(token.encode("utf-8")).hexdigest()


def remember_token_expires_at(
    *,
    now: datetime | None = None,
    lifetime_days: int = REMEMBER_TOKEN_LIFETIME_DAYS,
) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(days=max(1, int(lifetime_days)))


def remember_token_is_expired(
    raw_expires_at: str | datetime | None,
    *,
    now: datetime | None = None,
) -> bool:
    if raw_expires_at is None:
        return True
    if isinstance(raw_expires_at, datetime):
        expires_at = raw_expires_at
    else:
        try:
            expires_at = datetime.fromisoformat(str(raw_expires_at))
        except ValueError:
            return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base >= expires_at


def lockout_seconds_for_failure_count(
    failed_count: int,
    *,
    threshold: int = LOGIN_FAILURE_LOCK_THRESHOLD,
    lockout_seconds: int = LOGIN_LOCKOUT_SECONDS,
    lockout_schedule: Iterable[tuple[int, int]] | None = LOGIN_LOCKOUT_SCHEDULE,
) -> int | None:
    if failed_count < int(threshold):
        return None
    if not lockout_schedule:
        return int(lockout_seconds)

    selected: int | None = None
    for failure_threshold, seconds in sorted(lockout_schedule, key=lambda item: item[0]):
        if failed_count >= int(failure_threshold):
            selected = int(seconds)
    return selected if selected is not None else int(lockout_seconds)


def lockout_until_for_failure_count(
    failed_count: int,
    *,
    now: datetime | None = None,
    threshold: int = LOGIN_FAILURE_LOCK_THRESHOLD,
    lockout_seconds: int = LOGIN_LOCKOUT_SECONDS,
    lockout_schedule: Iterable[tuple[int, int]] | None = LOGIN_LOCKOUT_SCHEDULE,
) -> datetime | None:
    duration = lockout_seconds_for_failure_count(
        failed_count,
        threshold=threshold,
        lockout_seconds=lockout_seconds,
        lockout_schedule=lockout_schedule,
    )
    if duration is None:
        return None
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(seconds=duration)


def password_change_due(
    changed_at: datetime | None,
    *,
    now: datetime | None = None,
    reminder_days: int = 90,
) -> bool:
    if changed_at is None:
        return True
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    return base - changed_at >= timedelta(days=max(1, int(reminder_days)))
