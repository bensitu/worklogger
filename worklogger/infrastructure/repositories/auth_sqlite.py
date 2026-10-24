"""SQLite authentication repositories."""

from __future__ import annotations

import sqlite3
from worklogger.config.constants import GETTING_STARTED_PENDING_SETTING_KEY
from dataclasses import replace
from datetime import datetime, timezone

from worklogger.domain.auth.models import LinkedIdentity, User
from worklogger.domain.auth.policies import (
    generate_initial_password,
    generate_recovery_key,
    normalize_username,
    require_new_username,
    recovery_key_candidates,
    remember_token_is_expired,
    username_key,
)
from worklogger.domain.auth.profile import normalize_display_name
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import (
    bool_from_row,
    parse_datetime,
    utc_now_iso,
)
from worklogger.infrastructure.security.password_hasher import PBKDF2PasswordHasher

_DUMMY_PASSWORD_SALT = "00" * 16
_DUMMY_PASSWORD_HASH = "00" * 32


from worklogger.infrastructure.repositories.identity_sqlite import SQLiteIdentityRepository as SQLiteIdentityRepository
from worklogger.infrastructure.repositories.identity_sqlite import identity_from_row
from worklogger.infrastructure.repositories.login_failures_sqlite import (
    SQLiteLoginFailureRepository as SQLiteLoginFailureRepository,
)


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

    def register_user(self, username: str, password: str, *, recovery_key: str) -> User:
        return self._create_user(username, password, recovery_key=recovery_key, is_admin=False,
                                 self_registration=True)

    def create_user(self, username: str, password: str, *, recovery_key: str | None,
                    is_admin: bool, must_change_password: bool = False,
                    local_password_enabled: bool = True) -> User:
        return self._create_user(username, password, recovery_key=recovery_key, is_admin=is_admin,
            must_change_password=must_change_password, local_password_enabled=local_password_enabled)

    def _create_user(
        self,
        username: str,
        password: str,
        *,
        recovery_key: str | None,
        is_admin: bool,
        must_change_password: bool = False,
        local_password_enabled: bool = True,
        self_registration: bool = False,
    ) -> User:
        username = require_new_username(username)
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
        values = {
            "username": username, "password_hash": password_hash.hash_hex,
            "password_salt": password_hash.salt_hex, "recovery_key_hash": recovery_hash,
            "recovery_salt": recovery_salt, "is_admin": int(is_admin),
            "must_change_password": int(must_change_password), "created_at": now,
            "password_changed_at": now, "recovery_key_created_at": recovery_created_at,
        }
        values.update(username_key=username_key(username), local_password_enabled=int(local_password_enabled))
        try:
            with self._connection_factory.transaction(write=True) as connection:
                if self_registration:
                    values["is_admin"] = int(connection.execute("SELECT 1 FROM users LIMIT 1").fetchone() is None)
                cursor = connection.execute(
                    f"INSERT INTO users({', '.join(values)}) VALUES({', '.join('?' for _ in values)})",
                    tuple(values.values()),
                )
                user_id = int(cursor.lastrowid)
                self._initialize_account_preferences(connection, user_id)
        except sqlite3.IntegrityError as exc:
            if getattr(exc, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_UNIQUE":
                raise ValueError("username_exists") from exc
            raise
        user = self.get_by_id(user_id)
        if user is None:
            raise RuntimeError("created_user_not_found")
        return user

    def create_identity_account(self, username, profile):
        username = require_new_username(username)
        material = self._password_hasher.hash_password(generate_initial_password())
        now = utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            existing = connection.execute(
                "SELECT * FROM external_identities WHERE provider=? AND subject=?",
                (profile.provider, profile.subject)).fetchall()
            if len(existing) > 1:
                raise ValueError("identity_subject_ambiguous")
            if existing:
                linked = identity_from_row(existing[0])
                if profile.issuer and linked.issuer != profile.issuer:
                    raise ValueError("identity_issuer_mismatch")
                row = connection.execute("SELECT * FROM users WHERE id=?", (linked.user_id,)).fetchone()
                if row is None:
                    raise ValueError("identity_user_missing")
                return self._user_from_row(row), linked
            try:
                cursor = connection.execute(
                    "INSERT INTO users(username,username_key,password_hash,password_salt,is_admin,"
                    "must_change_password,created_at,password_changed_at,local_password_enabled) VALUES(?,?,?,?,0,0,?,?,0)",
                    (username, username_key(username), material.hash_hex, material.salt_hex, now, now))
            except sqlite3.IntegrityError as exc:
                if getattr(exc, "sqlite_errorname", "") == "SQLITE_CONSTRAINT_UNIQUE":
                    raise ValueError("username_exists") from exc
                raise
            user_id = int(cursor.lastrowid)
            self._initialize_account_preferences(connection, user_id)
            cursor = connection.execute(
                "INSERT INTO external_identities(user_id,provider,subject,email,display_name,created_at,updated_at,broker,issuer) "
                "VALUES(?,?,?,?,?,?,?,'direct_oidc',?)",
                (user_id, profile.provider, profile.subject, profile.email, profile.display_name, now, now,
                 profile.issuer or profile.provider))
            linked = LinkedIdentity(int(cursor.lastrowid), user_id, profile.provider, profile.subject,
                                    profile.email, profile.display_name, profile.issuer or profile.provider)
            user = self._user_from_row(connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())
        return user, linked

    @staticmethod
    def _initialize_account_preferences(connection, user_id):
        connection.execute("INSERT INTO settings(user_id,key,value) VALUES(?,?,?)",
                           (user_id, GETTING_STARTED_PENDING_SETTING_KEY, "1"))

    def set_display_name(self, user_id: int, display_name: str, *, expected_display_name: str) -> User:
        name = normalize_display_name(display_name)
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(
                "UPDATE users SET display_name=? WHERE id=? AND COALESCE(display_name,'')=?",
                (name, user_id, expected_display_name))
            row = connection.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise ValueError("user_not_found")
            if cursor.rowcount != 1:
                raise ValueError("user_profile_conflict")
            return self._user_from_row(row)

    def verify_user(self, username: str, password: str) -> User | None:
        try:
            username = normalize_username(username)
        except (TypeError, ValueError):
            return None
        with self._connection_factory.connection() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE username_key=?", (username_key(username),),
            ).fetchone()
        if row is None or not row["local_password_enabled"]:
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
        return self._complete_password_login(row, password, upgrade=verification.needs_upgrade)

    def verify_dummy_password(self, password: str) -> None:
        self._password_hasher.verify(password, _DUMMY_PASSWORD_HASH, _DUMMY_PASSWORD_SALT)

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
        return self._reset_password(user_id, new_password, must_change_password=False,
                                    expected_password=(row["password_hash"], row["password_salt"]))

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
                "SELECT * FROM users WHERE username_key=?", (username_key(username),),
            ).fetchone()
        if row is None or not row["recovery_key_hash"] or not row["recovery_salt"]:
            self._password_hasher.verify(
                cleaned_key,
                _DUMMY_PASSWORD_HASH,
                _DUMMY_PASSWORD_SALT,
            )
            return None
        if not any(self._password_hasher.verify(candidate, str(row["recovery_key_hash"]),
                   str(row["recovery_salt"])).matched for candidate in recovery_key_candidates(cleaned_key)):
            return None
        user_id = int(row["id"])
        new_recovery_key = self._reset_password(
            user_id,
            new_password,
            must_change_password=False,
            expected_recovery=(row["recovery_key_hash"], row["recovery_salt"]),
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
            must_change_password=bool(must_change_password),
            issue_recovery_key=False,
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
                    "DELETE FROM login_attempts WHERE username IN (?,?)",
                    (username_key(username), "\0recovery:" + username_key(username)),
                )
            connection.execute("UPDATE activity_events SET user_id=NULL WHERE user_id=?", (user_id,))
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
        with self._connection_factory.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM users WHERE remember_token=?",
                (stored_token,),
            ).fetchone()
            if row is None:
                return None
            if remember_token_is_expired(row["remember_token_expires_at"]):
                connection.execute("UPDATE users SET remember_token=NULL,remember_token_expires_at=NULL WHERE id=?", (row["id"],))
                return None
            user = self._user_from_row(row)
            now = datetime.now(timezone.utc)
            connection.execute("UPDATE users SET last_login_at=? WHERE id=?", (now.isoformat(), user.id))
            return replace(user, last_login_at=now)

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
                "SELECT * FROM users WHERE username_key=?", (username_key(username),),
            ).fetchone()
        return self._user_from_row(row) if row else None

    def list_users(self) -> tuple[User, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM users ORDER BY username COLLATE NOCASE",
            ).fetchall()
        return tuple(self._user_from_row(row) for row in rows)

    def _complete_password_login(self, expected, password: str, *, upgrade: bool) -> User | None:
        material = self._password_hasher.hash_password(password) if upgrade else None
        now = datetime.now(timezone.utc)
        with self._connection_factory.transaction(write=True) as connection:
            current = connection.execute(
                "SELECT * FROM users WHERE id=? AND password_hash=? AND password_salt=? AND local_password_enabled=1",
                (expected["id"], expected["password_hash"], expected["password_salt"]),
            ).fetchone()
            if current is None:
                return None
            if material is not None:
                connection.execute("UPDATE users SET password_hash=?,password_salt=? WHERE id=?",
                                   (material.hash_hex, material.salt_hex, current["id"]))
            connection.execute(
                "UPDATE users SET last_login_at=? WHERE id=?", (now.isoformat(), current["id"]),
            )
            return replace(self._user_from_row(current), last_login_at=now)

    def _reset_password(
        self,
        user_id: int,
        new_password: str,
        *,
        must_change_password: bool,
        issue_recovery_key: bool = True,
        expected_password: tuple[str, str] | None = None,
        expected_recovery: tuple[str, str] | None = None,
    ) -> str | None:
        password_material = self._password_hasher.hash_password(new_password)
        recovery_key = generate_recovery_key() if issue_recovery_key else None
        recovery_material = self._password_hasher.hash_password(recovery_key) if recovery_key else None
        now = utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            conditions = ""
            expected_values = ()
            for columns, values in ((("password_hash", "password_salt"), expected_password),
                                    (("recovery_key_hash", "recovery_salt"), expected_recovery)):
                if values is not None:
                    conditions += " AND " + " AND ".join(column + "=?" for column in columns)
                    expected_values += values
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
                """ + conditions,
                (
                    password_material.hash_hex,
                    password_material.salt_hex,
                    recovery_material.hash_hex if recovery_material else None,
                    recovery_material.salt_hex if recovery_material else None,
                    now if recovery_material else None,
                    now,
                    1 if must_change_password else 0,
                    user_id,
                ) + expected_values,
            )
            if cursor.rowcount:
                connection.execute("UPDATE users SET local_password_enabled=1 WHERE id=?", (user_id,))
                connection.execute("DELETE FROM login_attempts WHERE username=(SELECT username_key FROM users WHERE id=?) "
                    "OR username=char(0)||'recovery:'||(SELECT username_key FROM users WHERE id=?)", (user_id, user_id))
        return (recovery_key if issue_recovery_key else new_password) if cursor.rowcount else None

    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> User:
        return User(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or ""),
            is_admin=bool_from_row(row, "is_admin"),
            must_change_password=bool_from_row(row, "must_change_password"),
            created_at=parse_datetime(row["created_at"]),
            password_changed_at=parse_datetime(row["password_changed_at"]),
            recovery_key_created_at=parse_datetime(row["recovery_key_created_at"]),
            last_login_at=parse_datetime(row["last_login_at"]),
            local_password_enabled=bool_from_row(row, "local_password_enabled"),
        )
