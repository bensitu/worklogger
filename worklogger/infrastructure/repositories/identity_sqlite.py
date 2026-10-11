"""Account-scoped linked identity storage and row conversion."""

from __future__ import annotations

import sqlite3

from worklogger.domain.auth.models import LinkedIdentity
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import utc_now_iso


class SQLiteIdentityRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def list_for_user(self, user_id: int) -> tuple[LinkedIdentity, ...]:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM external_identities WHERE user_id=? ORDER BY provider, id",
                (user_id,),
            ).fetchall()
        return tuple(identity_from_row(row) for row in rows)

    def get_by_provider_subject(
        self,
        provider: str,
        subject: str,
    ) -> LinkedIdentity | None:
        with self._connection_factory.connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM external_identities
                WHERE provider=? AND subject=? LIMIT 2
                """,
                (str(provider), str(subject)),
            ).fetchall()
        if len(rows) > 1:
            raise ValueError("identity_subject_ambiguous")
        return identity_from_row(rows[0]) if rows else None

    def add(self, identity: LinkedIdentity) -> LinkedIdentity:
        now = utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(
                """
                INSERT INTO external_identities(
                    user_id, provider, subject, email, display_name, created_at, updated_at, broker, issuer
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identity.user_id,
                    identity.provider,
                    identity.subject,
                    identity.email,
                    identity.display_name,
                    now,
                    now,
                    "direct_oidc",
                    identity.issuer or identity.provider,
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
            issuer=identity.issuer or identity.provider,
        )

    def remove(self, user_id: int, identity_id: int) -> None:
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM external_identities WHERE user_id=? AND id=?",
                (user_id, identity_id),
            )


def identity_from_row(row: sqlite3.Row) -> LinkedIdentity:
    return LinkedIdentity(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        provider=str(row["provider"]),
        subject=str(row["subject"]),
        email=row["email"],
        display_name=row["display_name"],
        issuer=str(row["issuer"] or ""),
    )
