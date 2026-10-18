"""Account-isolated custom classifications with optimistic updates."""

from dataclasses import replace
import unicodedata
import sqlite3
from worklogger.domain.worklog.models import CustomEntryType, CustomWorkMode


class SQLiteClassificationRepository:
    table: str
    error_prefix: str

    def __init__(self, connection_factory):
        self._connection_factory = connection_factory

    def list_types(self, user_id):
        with self._connection_factory.connection() as connection:
            rows = connection.execute(f"SELECT * FROM {self.table} WHERE user_id=? ORDER BY archived,name,id", (user_id,)).fetchall()
        return tuple(self._definition(row) for row in rows)

    def save_type(self, user_id, definition):
        normalized = unicodedata.normalize("NFKC", definition.label.strip()).casefold()
        try:
            with self._connection_factory.transaction(write=True) as connection:
                row = connection.execute(f"SELECT user_id,revision,archived FROM {self.table} WHERE id=?", (definition.value,)).fetchone()
                if row is None:
                    connection.execute(f"INSERT INTO {self.table}(id,user_id,name,normalized_name,category) VALUES(?,?,?,?,?)",
                                       (definition.value, user_id, definition.label.strip(), normalized, definition.category))
                    return definition
                if row["user_id"] != user_id or row["revision"] != definition.revision or row["archived"]:
                    raise ValueError(self.error_prefix + "_conflict")
                connection.execute(f"UPDATE {self.table} SET name=?,normalized_name=?,category=?,revision=revision+1 WHERE id=? AND user_id=?",
                                   (definition.label.strip(), normalized, definition.category, definition.value, user_id))
                return replace(definition, revision=definition.revision + 1)
        except sqlite3.IntegrityError as error:
            if getattr(error, "sqlite_errorcode", None) == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise ValueError(self.error_prefix + "_name_exists") from None
            raise

    def archive_type(self, user_id, definition):
        with self._connection_factory.transaction(write=True) as connection:
            cursor = connection.execute(f"UPDATE {self.table} SET archived=1,revision=revision+1 WHERE id=? AND user_id=? AND revision=?",
                                        (definition.value, user_id, definition.revision))
            if cursor.rowcount != 1:
                raise ValueError(self.error_prefix + "_conflict")


class SQLiteEntryTypeRepository(SQLiteClassificationRepository):
    table = "entry_types"
    error_prefix = "entry_type"

    @staticmethod
    def _definition(row):
        return CustomEntryType(row["id"], row["name"], row["category"], row["revision"], bool(row["archived"]))


class SQLiteWorkModeRepository(SQLiteClassificationRepository):
    table = "work_modes"
    error_prefix = "work_mode"

    @staticmethod
    def _definition(row):
        return CustomWorkMode(row["id"], row["name"], row["revision"], bool(row["archived"]))
