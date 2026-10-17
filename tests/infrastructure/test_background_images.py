"""Background validation, ownership, migration, and snapshot preservation."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtGui import QColor, QImage

from tests.background_samples import animated_background_bytes
from worklogger.app.use_cases.backgrounds import BackgroundService
from worklogger.domain.settings.background import BackgroundState
from worklogger.infrastructure.backup.sqlite_backup import SQLiteBackupService
from worklogger.infrastructure.database import MigrationRunner, SQLiteConnectionFactory
from worklogger.infrastructure.database.inspection import validate_database_file
from worklogger.infrastructure.images.background import (
    QtBackgroundImageLoader,
    validate_background_data,
)
from worklogger.infrastructure.repositories import (
    SQLiteAuthRepository,
)
from worklogger.infrastructure.repositories.background_sqlite import (
    SQLiteBackgroundRepository,
)
from worklogger.infrastructure.security import PBKDF2PasswordHasher


class BackgroundImageTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.factory = SQLiteConnectionFactory(self.directory / "source.db")
        MigrationRunner(self.factory).run_pending()
        self.auth = SQLiteAuthRepository(self.factory, password_hasher=PBKDF2PasswordHasher(iterations=1000))
        self.users = [self.auth.create_user(name, "example-password", recovery_key=None, is_admin=False)
                      for name in ("sample.one", "sample.two")]
        self.repository = SQLiteBackgroundRepository(self.factory)
        self.service = BackgroundService(self.users[0].id, self.repository, QtBackgroundImageLoader())

    def source_image(self, width=1280, height=720, format_name="PNG"):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#36b5a1"))
        path = self.directory / ("source." + format_name.lower())
        self.assertTrue(image.save(str(path), format_name))
        return path

    def test_import_preferences_replacement_and_clear_are_account_scoped(self):
        self.assertEqual(self.service.load().value, BackgroundState())
        self.assertEqual(self.service.set_options(enabled=True, opacity=50).value, BackgroundState(enabled=True))
        imported = self.service.import_image(str(self.source_image())).value
        self.assertTrue(imported.enabled)
        self.assertEqual(imported.opacity, 50)
        self.assertNotIn("data=", repr(imported.image))
        self.assertEqual(self.repository.load(self.users[1].id), BackgroundState())
        for opacity in (0, 35, 50, 100):
            changed = self.service.set_options(enabled=True, opacity=opacity)
            self.assertTrue(changed.ok, changed.error)
            self.assertEqual(changed.value.opacity, opacity)
        replacement = self.service.import_image(str(self.source_image(720, 1280, "JPEG")))
        self.assertTrue(replacement.ok, replacement.error)
        self.assertTrue(replacement.value.enabled)
        self.assertEqual(replacement.value.opacity, 100)
        self.assertEqual(replacement.value.image.format, "jpeg")
        self.assertEqual(self.service.clear().value, BackgroundState(enabled=True, opacity=100))
        self.assertEqual(self.repository.load(self.users[1].id), BackgroundState())

    def test_invalid_images_and_failed_writes_preserve_previous_content(self):
        original = self.service.import_image(str(self.source_image())).value
        for value in (-1, 101, 50.5, True, "50"):
            self.assertEqual(self.service.set_options(enabled=True, opacity=value).error.code, "background_opacity_invalid")
        self.assertFalse(self.service.set_options(enabled="yes", opacity=50).ok)
        self.assertEqual(self.service.import_image(str(self.source_image(1279, 720))).error.code,
                         "background_image_resolution_low")
        self.assertFalse(self.service.import_image(str(self.directory)).ok)
        self.assertFalse(self.service.import_image(str(self.directory / "missing.png")).ok)
        invalid = self.directory / "invalid.png"
        invalid.write_bytes(b"not an image")
        self.assertEqual(self.service.import_image(str(invalid)).error.code, "background_image_invalid")
        with patch.object(self.repository, "replace_image", side_effect=OSError("storage unavailable")):
            self.assertEqual(self.service.import_image(str(self.source_image())).error.code, "background_storage_failed")
        self.assertEqual(self.service.load().value, original)

    def test_animation_is_fully_decoded_and_bounded_before_storage(self):
        data = animated_background_bytes()
        image = validate_background_data(data)
        self.assertEqual((image.format, image.width, image.height, image.frames), ("webp", 1280, 720, 2))
        self.assertTrue(image.animated)
        with self.assertRaisesRegex(ValueError, "background_image_invalid"):
            validate_background_data(data[:-12])
        with patch("worklogger.infrastructure.images.background.MAX_BACKGROUND_FRAMES", 1), self.assertRaisesRegex(
            ValueError, "background_animation_too_large"
        ):
            validate_background_data(data)
        with patch("worklogger.infrastructure.images.background.MAX_BACKGROUND_BYTES", 100), self.assertRaisesRegex(
            ValueError, "background_image_too_large"
        ):
            validate_background_data(data)
        self.repository.replace_image(self.users[0].id, image)
        self.assertEqual(self.service.load().value.image.data, data)

    def test_database_backup_preserves_media_and_account_deletion_cascades(self):
        self.repository.replace_image(self.users[0].id, validate_background_data(animated_background_bytes()))
        expected = self.service.set_options(enabled=True, opacity=65).value
        backup = self.directory / "backup.db"
        self.assertTrue(SQLiteBackupService(self.factory).backup_database(backup).ok)
        validate_database_file(backup)
        restored = SQLiteBackgroundRepository(SQLiteConnectionFactory(backup))
        self.assertEqual(restored.load(self.users[0].id), expected)
        with self.factory.transaction() as connection:
            connection.execute("DELETE FROM users WHERE id=?", (self.users[0].id,))
        self.assertEqual(self.service.load().value, BackgroundState())
