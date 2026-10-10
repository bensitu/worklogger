"""Add optional account backgrounds without rewriting existing records."""

VERSION = 14
DESCRIPTION = "background_images"


def up(connection):
    connection.execute("""CREATE TABLE IF NOT EXISTS background_images(
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        data BLOB, format TEXT, width INTEGER, height INTEGER, frames INTEGER,
        enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
        opacity INTEGER NOT NULL DEFAULT 50 CHECK(opacity BETWEEN 0 AND 100),
        CHECK(data IS NOT NULL OR enabled=0),
        CHECK((data IS NULL AND format IS NULL AND width IS NULL AND height IS NULL AND frames IS NULL)
            OR (data IS NOT NULL AND format IS NOT NULL AND width IS NOT NULL
            AND height IS NOT NULL AND frames IS NOT NULL AND length(data) BETWEEN 1 AND 20971520
            AND format IN ('png','jpeg','webp','gif') AND width >= 720 AND height >= 720
            AND (width >= 1280 OR height >= 1280) AND width*height <= 16000000
            AND frames BETWEEN 1 AND 300 AND width*height*frames <= 128000000)))""")
