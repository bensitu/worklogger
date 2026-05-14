"""SQLite report template repository."""

from __future__ import annotations

import sqlite3

from worklogger.domain.reporting.templates import (
    ReportTemplate,
    normalize_template_language,
    normalize_template_type,
)
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory
from worklogger.infrastructure.repositories._mapping import parse_datetime, utc_now_iso


class SQLiteReportTemplateRepository:
    def __init__(self, connection_factory: SQLiteConnectionFactory) -> None:
        self._connection_factory = connection_factory

    def save(self, template: ReportTemplate) -> ReportTemplate:
        language = normalize_template_language(template.language)
        template_type = normalize_template_type(template.template_type)
        updated_at = template.updated_at.isoformat(timespec="seconds") if template.updated_at else utc_now_iso()
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                """
                INSERT INTO report_templates(user_id, language, type, content, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id, language, type) DO UPDATE SET
                    content=excluded.content,
                    updated_at=excluded.updated_at
                """,
                (
                    template.user_id,
                    language,
                    template_type,
                    template.content,
                    updated_at,
                ),
            )
            row = self._select(connection, template.user_id, language, template_type)
        assert row is not None
        return self._from_row(row)

    def get(
        self,
        user_id: int,
        language: str,
        template_type: str,
    ) -> ReportTemplate | None:
        normalized_language = normalize_template_language(language)
        normalized_type = normalize_template_type(template_type)
        with self._connection_factory.connection() as connection:
            row = self._select(connection, user_id, normalized_language, normalized_type)
        return self._from_row(row) if row else None

    def list_for_user(
        self,
        user_id: int,
        language: str | None = None,
    ) -> tuple[ReportTemplate, ...]:
        with self._connection_factory.connection() as connection:
            if language is None:
                rows = connection.execute(
                    """
                    SELECT * FROM report_templates
                    WHERE user_id=?
                    ORDER BY language, type
                    """,
                    (user_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM report_templates
                    WHERE user_id=? AND language=?
                    ORDER BY type
                    """,
                    (user_id, normalize_template_language(language)),
                ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def remove(self, user_id: int, language: str, template_type: str) -> None:
        normalized_language = normalize_template_language(language)
        normalized_type = normalize_template_type(template_type)
        with self._connection_factory.transaction(write=True) as connection:
            connection.execute(
                "DELETE FROM report_templates WHERE user_id=? AND language=? AND type=?",
                (user_id, normalized_language, normalized_type),
            )

    @staticmethod
    def _select(
        connection: sqlite3.Connection,
        user_id: int,
        language: str,
        template_type: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT * FROM report_templates
            WHERE user_id=? AND language=? AND type=?
            LIMIT 1
            """,
            (user_id, language, template_type),
        ).fetchone()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ReportTemplate:
        return ReportTemplate(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            language=str(row["language"]),
            template_type=str(row["type"]),
            content=str(row["content"]),
            updated_at=parse_datetime(row["updated_at"]),
        )

