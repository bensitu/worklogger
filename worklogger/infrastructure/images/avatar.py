"""Normalize account avatars without retaining source paths or metadata."""

from pathlib import Path
import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter

from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


def load_avatar_image(source):
    try:
        path = Path(source)
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("avatar_image_too_large")
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if bytes(reader.format()).lower() not in {
            b"png",
            b"jpeg",
            b"jpg",
            b"webp",
            b"bmp",
        }:
            raise ValueError("avatar_image_invalid")
        if not size.isValid() or size.width() * size.height() > 20_000_000:
            raise ValueError("avatar_image_too_large")
        image = reader.read()
        if image.isNull():
            raise ValueError("avatar_image_invalid")
        return Result.success(image)
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) else "avatar_image_invalid"
        return Result.failure(ValidationError(code, code))


def encode_avatar(image):
    normalized = image.scaled(
        256,
        256,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    pixels = QImage(256, 256, QImage.Format.Format_RGBA8888)
    pixels.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixels)
    painter.drawImage(0, 0, normalized)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not pixels.save(buffer, "PNG"):
        raise ValueError("avatar_image_invalid")
    buffer.close()
    return base64.b64encode(bytes(data)).decode("ascii")


def decode_avatar(encoded):
    if not encoded or len(encoded) > 512 * 1024:
        return None
    try:
        data = QByteArray(base64.b64decode(encoded, validate=True))
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer, b"png")
        size = reader.size()
        if not size.isValid() or max(size.width(), size.height()) > 256:
            return None
        image = reader.read()
        return None if image.isNull() else image
    except (ValueError, TypeError):
        return None
