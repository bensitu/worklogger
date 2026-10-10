"""Bounded raster decoding for still and animated background imports."""

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImageReader

from worklogger.domain.settings.background import (
    BACKGROUND_FORMATS,
    MAX_BACKGROUND_BYTES,
    MAX_BACKGROUND_FRAME_PIXELS,
    MAX_BACKGROUND_FRAMES,
    MAX_BACKGROUND_TOTAL_PIXELS,
    BackgroundImage,
)
from worklogger.domain.shared.errors import ValidationError
from worklogger.domain.shared.result import Result


class QtBackgroundImageLoader:
    def load(self, source: str) -> Result[BackgroundImage]:
        try:
            path = Path(source)
            if not path.is_file():
                raise ValueError("background_image_invalid")
            if path.stat().st_size > MAX_BACKGROUND_BYTES:
                raise ValueError("background_image_too_large")
            with path.open("rb") as stream:
                data = stream.read(MAX_BACKGROUND_BYTES + 1)
            return Result.success(validate_background_data(data))
        except (OSError, TypeError):
            return Result.failure(ValidationError("background_image_invalid", "background_image_invalid"))
        except ValueError as error:
            return Result.failure(ValidationError(str(error), str(error)))


def validate_background_data(data: bytes) -> BackgroundImage:
    if not data or len(data) > MAX_BACKGROUND_BYTES:
        raise ValueError("background_image_too_large" if data else "background_image_invalid")
    buffer = QBuffer()
    buffer.setData(QByteArray(data))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    reader.setAutoTransform(True)
    format_name = bytes(reader.format()).decode("ascii", errors="replace").lower()
    if format_name not in BACKGROUND_FORMATS:
        raise ValueError("background_image_invalid")
    size = reader.size()
    declared_frames = reader.imageCount()
    candidate = BackgroundImage(data, format_name, size.width(), size.height(), max(1, declared_frames))
    frames, pixels = 0, 0
    while reader.canRead():
        next_size = reader.size()
        if next_size.width() * next_size.height() > MAX_BACKGROUND_FRAME_PIXELS:
            raise ValueError("background_image_too_large")
        frame = reader.read()
        if frame.isNull():
            raise ValueError("background_image_invalid")
        frames += 1
        pixels += frame.width() * frame.height()
        if frames > MAX_BACKGROUND_FRAMES or pixels > MAX_BACKGROUND_TOTAL_PIXELS:
            raise ValueError("background_animation_too_large")
        if not reader.supportsAnimation():
            break
    if not frames or declared_frames > 0 and frames != declared_frames:
        raise ValueError("background_image_invalid")
    return BackgroundImage(data, format_name, candidate.width, candidate.height, frames)
