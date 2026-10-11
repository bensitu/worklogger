"""Transactional account media storage included in database backups."""

from worklogger.domain.settings.background import (
    BackgroundImage,
    BackgroundState,
    validate_opacity,
)
from worklogger.infrastructure.database.connection import SQLiteConnectionFactory


class SQLiteBackgroundRepository:
    def __init__(self, factory: SQLiteConnectionFactory):
        self._factory = factory

    def load(self, user_id: int) -> BackgroundState:
        with self._factory.connection() as connection:
            return self._load(connection, user_id)

    def replace_image(self, user_id: int, image: BackgroundImage) -> BackgroundState:
        with self._factory.transaction() as connection:
            connection.execute("""INSERT INTO background_images(user_id,data,format,width,height,frames)
                VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,
                format=excluded.format,width=excluded.width,height=excluded.height,frames=excluded.frames""",
                (user_id, image.data, image.format, image.width, image.height, image.frames))
            return self._load(connection, user_id)

    def set_options(self, user_id: int, *, enabled: bool, opacity: int) -> BackgroundState:
        validate_opacity(opacity)
        with self._factory.transaction() as connection:
            connection.execute("INSERT OR IGNORE INTO background_images(user_id) VALUES(?)", (user_id,))
            connection.execute("UPDATE background_images SET enabled=?,opacity=? WHERE user_id=?",
                               (int(enabled), opacity, user_id))
            return self._load(connection, user_id)

    def clear(self, user_id: int) -> BackgroundState:
        with self._factory.transaction() as connection:
            connection.execute("""UPDATE background_images SET data=NULL,format=NULL,width=NULL,
                height=NULL,frames=NULL WHERE user_id=?""", (user_id,))
            return self._load(connection, user_id)

    @staticmethod
    def _load(connection, user_id: int) -> BackgroundState:
        row = connection.execute("SELECT * FROM background_images WHERE user_id=?", (user_id,)).fetchone()
        if row is None:
            return BackgroundState()
        image = (BackgroundImage(bytes(row["data"]), row["format"], row["width"], row["height"], row["frames"])
                 if row["data"] is not None else None)
        return BackgroundState(image, bool(row["enabled"]), row["opacity"])
