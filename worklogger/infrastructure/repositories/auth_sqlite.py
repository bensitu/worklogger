"""SQLite authentication repositories."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3

from worklogger.domain.auth.models import LinkedIdentity, User
from worklogger.domain.auth.policies import (
    generate_recovery_key,
    lockout_until_for_failure_count,
    normalize_username,
    remember_token_is_expired,
)
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import (
    bool_from_row,
    parse_datetime,
    utc_now_iso,
)
from worklogger.infrastructure.security.password_hasher import PBKDF2PasswordHasher

_DUMMY_PASSWORD_SALT = "00" * 16
_DUMMY_PASSWORD_HASH = "00" * 32


class SQLiteAuthRepository:
    def __init__(
        self,
        connection_factory: SQLiteConnectionFactory,
        *,
        password_hasher: PBKDF2PasswordHasher | None = None,
    ) -> None:
        self._connection_factory = connection_factory
        self._password_hasher = password_hasher or PBKDF2PasswordHasher()

    def user_count(self) -> int:
        with self._connection_factory.connection() as connection:
            row = connection.execute("SELECT COUNT(*) FROM users").fetchone()
            return int(row[0])

    def create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None,
        is_admin: bool,
        must_change_password: bool = False,
    ) -> User:
        username = normalize_username(username)
        password_hash = self._password_hasher.hash_password(password)
        recovery_hash = None
        recovery_salt = None
        recovery_created_at = None
        if recovery_key:
            material = self._password_hasher.hash_password(recovery_key.strip())
            recovery_hash = material.hash_hex
            recovery_salt = material.salt_hex
            recovery_created_at = utc_now_iso()
        now = utc_now_iso()
        try:
            with self._connection_factory.transaction(write=True) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO users(
                        username,
                        password_hash,
                        password_salt,
                        recovery_key_hash,
                        recovery_salt,
                        is_admin,
                        must_change_password,
                        created_at,
                        password_changed_at,
                        recovery_key_created_at
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        username,
                        password_hash.hash_hex,
                        password_hash.salt_hex,
                        recovery_hash,
                        recovery_salt,
                        1 if is_admin else 0,
                        1 if must_change_password else 0,
                        now,
                        now,
                        recovery_created_at,
                    ),
                )
                user_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise ValueError("username_exists") from exc
        user = self.get_by_id(user_id)
        if user is None:
            raise RuntimeError("created_user_not_found")
        return user

    def verify_user(self, username: str, password: str) -> User | None:
        try:
            username = normalize_username(username)
        except (TypeError, ValueError):
            return None
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=?",
                (username,),
            ).fetchone()
        if row is None:
            self._password_hasher.verify(
                password,
                _DUMMY_PASSWORD_HASH,
                _DUMMY_PASSWORD_SALT,
            )
            return None
        verification = self._password_hasher.verify(
            password,
            str(row["password_hash"]),
            str(row["password_salt"]),
        )
        if not verification.matched:
            return None
        user = self._user_from_row(row)
        if verification.needs_upgrade:
            self._replace_password_hash(user.id, password)
        return user

    def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> str | None:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        verification = self._password_hasher.verify(
            current_password,
            str(row["password_hash"]),
            str(row["password_salt"]),
        )
        if not verification.matched:
            return None
        return self._reset_password(user_id, new_password, must_change_password=False)

    def reset_password_with_recovery(
        self,
        username: str,
        recovery_key: str,
        new_password: str,
    ) -> tuple[User, str] | None:
        try:
            username = normalize_username(username)
        except (TypeError, ValueError):
            return None
        cleaned_key = recovery_key.strip() if isinstance(recovery_key, str) else ""
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=?",
                (username,),
            ).fetchone()
        if row is None or not row["recovery_key_hash"] or not row["recovery_salt"]:
            self._password_hasher.verify(
                cleaned_key,
                _DUMMY_PASSWORD_HASH,
                _DUMMY_PASSWORD_SALT,
            )
            return None
        verification = self._password_hasher.verify(
            cleaned_key,
            str(row["recovery_key_hash"]),
            str(row["recovery_salt"]),
        )
        if not verification.matched:
            return None
        user_id = int(row["id"])
        new_recovery_key = self._reset_password(
            user_id,
            new_password,
            must_change_password=False,
        )
        user = self.get_by_id(user_id)
        if user is None or new_recovery_key is None:
            return None
        return user, new_recovery_key

    def reset_password_by_admin(
        self,
        user_id: int,
        new_password: str,
        *,
        must_change_password: bool,
    ) -> str | None:
        if self.get_by_id(user_id) is None:
            return None
        return self._reset_password(
            user_id,
            new_password,
            must_change_password=must_change_password,
        )

    def set_password_change_required(self, user_id: int, required: bool) -> bool:
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET must_change_password=?,
                    remember_token=CASE WHEN ? THEN NULL ELSE remember_token END,
                    remember_token_expires_at=CASE
                        WHEN ? THEN NULL
                        ELSE remember_token_expires_at
                    END
                WHERE id=?
                """,
                (
                    1 if required else 0,
                    1 if required else 0,
                    1 if required else 0,
                    user_id,
                ),
            )
        return cursor.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        username = None
        user = self.get_by_id(user_id)
        if user is not None:
            username = user.username
        with self._connection_factory.transaction(write=True) as connection:
            if username is not None:
                connection.execute(
                    "DELETE FROM login_attempts WHERE username=?",
                    (username,),
                )
            cursor = connection.execute(
                "DELETE FROM users WHERE id=?",
                (user_id,),
            )
        return cursor.rowcount > 0

    def set_remember_token(
        self,
        user_id: int,
        stored_token: str | None,
        expires_at: datetime | None,
    ) -> None:
        expires_raw = expires_at.isoformat(timespec="seconds") if expires_at else None
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "UPDATE users SET remember_token=?, remember_token_expires_at=? WHERE id=?",
                (stored_token, expires_raw, user_id),
            )

    def get_user_by_remember_token(self, stored_token: str) -> User | None:
        if not stored_token:
            return None
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE remember_token=?",
                (stored_token,),
            ).fetchone()
        if row is None:
            return None
        if remember_token_is_expired(row["remember_token_expires_at"]):
            self.set_remember_token(int(row["id"]), None, None)
            return None
        return self._user_from_row(row)

    def get_by_id(self, user_id: int) -> User | None:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
        return self._user_from_row(row) if row else None

    def get_by_username(self, username: str) -> User | None:
        try:
            username = normalize_username(username)
        except (TypeError, ValueError):
            return None
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username=?",
                (username,),
            ).fetchone()
        return self._user_from_row(row) if row else None

    def list_users(self) -> tuple[User, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY username COLLATE NOCASE",
            ).fetchall()
        return tuple(self._user_from_row(row) for row in rows)

    def _replace_password_hash(self, user_id: int, password: str) -> None:
        material = self._password_hasher.hash_password(password)
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "UPDATE users SET password_hash=?, password_salt=? WHERE id=?",
                (material.hash_hex, material.salt_hex, user_id),
            )

    def _reset_password(
        self,
        user_id: int,
        new_password: str,
        *,
        must_change_password: bool,
    ) -> str | None:
        password_material = self._password_hasher.hash_password(new_password)
        recovery_key = generate_recovery_key()
        recovery_material = self._password_hasher.hash_password(recovery_key)
        now = utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                UPDATE users
                SET password_hash=?,
                    password_salt=?,
                    recovery_key_hash=?,
                    recovery_salt=?,
                    recovery_key_created_at=?,
                    password_changed_at=?,
                    must_change_password=?,
                    remember_token=NULL,
                    remember_token_expires_at=NULL
                WHERE id=?
                """,
                (
                    password_material.hash_hex,
                    password_material.salt_hex,
                    recovery_material.hash_hex,
                    recovery_material.salt_hex,
                    now,
                    now,
                    1 if must_change_password else 0,
                    user_id,
                ),
            )
        return recovery_key if cursor.rowcount else None

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> User:
        return User(
            id=int(row["id"]),
            username=str(row["username"]),
            is_admin=bool_from_row(row, "is_admin"),
            must_change_password=bool_from_row(row, "must_change_password"),
            created_at=parse_datetime(row["created_at"]),
            password_changed_at=parse_datetime(row["password_changed_at"]),
            recovery_key_created_at=parse_datetime(row["recovery_key_created_at"]),
            last_login_at=parse_datetime(row["last_login_at"]),
        )


class SQLiteLoginFailureRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def lockout_until(self, username: str) -> datetime | None:
        try:
            username = normalize_username(username)
        except (TypeError, ValueError):
            return None
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT locked_until FROM login_attempts WHERE username=?",
                (username,),
            ).fetchone()
        locked_until = parse_datetime(row["locked_until"]) if row else None
        if locked_until is None:
            return None
        if locked_until <= datetime.now(timezone.utc):
            with self._connection_factory.transaction(write=True) as connection:
                connection.execute(
                    "UPDATE login_attempts SET locked_until=NULL WHERE username=?",
                    (username,),
                )
            return None
        return locked_until

    def record_failure(self, username: str) -> tuple[int, datetime | None]:
        username = normalize_username(username)
        with self._connection_factory.transaction(write=True) as connection:
            row = connection.execute(
                "SELECT failed_count FROM login_attempts WHERE username=?",
                (username,),
            ).fetchone()
            failed_count = int(row["failed_count"]) + 1 if row else 1
            locked_until = lockout_until_for_failure_count(failed_count)
            locked_until_raw = locked_until.isoformat(timespec="seconds") if locked_until else None
            connection.execute(
                """
                INSERT INTO login_attempts(username, failed_count, locked_until, last_failed_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    failed_count=excluded.failed_count,
                    locked_until=excluded.locked_until,
                    last_failed_at=excluded.last_failed_at
                """,
                (username, failed_count, locked_until_raw, utc_now_iso()),
            )
        return failed_count, locked_until

    def clear_failures(self, username: str) -> None:
        try:
            username = normalize_username(username)
        except (TypeError, ValueError):
            return
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM login_attempts WHERE username=?",
                (username,),
            )


class SQLiteIdentityRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def list_for_user(self, user_id: int) -> tuple[LinkedIdentity, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM external_identities WHERE user_id=? ORDER BY provider, id",
                (user_id,),
            ).fetchall()
        return tuple(self._identity_from_row(row) for row in rows)

    def get_by_provider_subject(
        self,
        provider: str,
        subject: str,
    ) -> LinkedIdentity | None:
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                """
                SELECT * FROM external_identities
                WHERE provider=? AND subject=?
                """,
                (str(provider), str(subject)),
            ).fetchone()
        return self._identity_from_row(row) if row else None

    def add(self, identity: LinkedIdentity) -> LinkedIdentity:
        now = utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO external_identities(
                    user_id, provider, subject, email, display_name, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.user_id,
                    identity.provider,
                    identity.subject,
                    identity.email,
                    identity.display_name,
                    now,
                    now,
                ),
            )
            identity_id = int(cursor.lastrowid)
        return LinkedIdentity(
            id=identity_id,
            user_id=identity.user_id,
            provider=identity.provider,
            subject=identity.subject,
            email=identity.email,
            display_name=identity.display_name,
        )

    def remove(self, user_id: int, identity_id: int) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM external_identities WHERE user_id=? AND id=?",
                (user_id, identity_id),
            )

    @staticmethod
    def _identity_from_row(row: sqlite3.Row) -> LinkedIdentity:
        return LinkedIdentity(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            provider=str(row["provider"]),
            subject=str(row["subject"]),
            email=row["email"],
            display_name=row["display_name"],
        )
