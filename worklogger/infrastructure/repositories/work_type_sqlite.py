"""Account-isolated custom classifications with optimistic updates."""

from dataclasses import replace
import unicodedata
import sqlite3
from worklogger.domain.worklog.models import CustomWorkType


class SQLiteWorkTypeRepository:
    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def list_types(self, user_id):
        with self._connection_factory.connection() as connection:
            rows = connection.execute("SELECT * FROM work_types WHERE user_id=? ORDER BY archived,name,id", (user_id,)).fetchall()
        return tuple(CustomWorkType(row["id"], row["name"], row["category"], row["revision"], bool(row["archived"])) for row in rows)

    def save_type(self, user_id, definition):
        normalized = unicodedata.normalize("NFKC", definition.label.strip()).casefold()
        try:
            with self._connection_factory.transaction(write=True) as connection:
                row = connection.execute("SELECT user_id,revision FROM work_types WHERE id=?", (definition.value,)).fetchone()
                if row is None:
                    connection.execute("INSERT INTO work_types(id,user_id,name,normalized_name,category) VALUES(?,?,?,?,?)",
                                       (definition.value, user_id, definition.label.strip(), normalized, definition.category))
                    return definition
                if row["user_id"] != user_id or row["revision"] != definition.revision:
                    raise ValueError("work_type_conflict")
                connection.execute("UPDATE work_types SET name=?,normalized_name=?,category=?,revision=revision+1 WHERE id=? AND user_id=?",
                                   (definition.label.strip(), normalized, definition.category, definition.value, user_id))
                return replace(definition, revision=definition.revision + 1)
        except sqlite3.IntegrityError:
            raise ValueError("work_type_name_exists") from None

    def archive_type(self, user_id, definition):
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute("UPDATE work_types SET archived=1,revision=revision+1 WHERE id=? AND user_id=? AND revision=?",
                                        (definition.value, user_id, definition.revision))
            if cursor.rowcount != 1:
                raise ValueError("work_type_conflict")
