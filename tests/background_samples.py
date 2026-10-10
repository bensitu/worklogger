"""Small encoded media fixtures without an additional imaging dependency."""

import base64


def animated_background_bytes():
    # Two lossless 1280-by-720 WebP frames with an 80 ms delay and infinite looping.
    return base64.b64decode(
        "UklGRogAAABXRUJQVlA4WAoAAAACAAAA/wQAzwIAQU5JTQYAAAAAAAAAAABBTk1GKgAAAAAA"
        "AAAAAP8EAM8CAFAAAAJWUDhMEQAAAC//xLMAB9Choteu/4GI6H8AAEFOTUYqAAAAAAAAAAAA"
        "/wQAzwIAUAAAAFZQOEwRAAAAL//EswAH0NraNLT/gYjofwAA"
    )


def still_background_bytes():
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QColor, QImage

    image = QImage(1280, 720, QImage.Format.Format_RGB32)
    image.fill(QColor("#36b5a1"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("fixture_image_failed")
    return bytes(buffer.data())


def animated_gif_background_bytes():
    # A 1280-by-720 GIF canvas with a small animated mark and infinite looping.
    return base64.b64decode(
        "R0lGODlhAAXQAoEAAOhDdgAAAAAAAAAAACH/C05FVFNDQVBFMi4wAwEAAAAh+QQACAAAACwAAAAA"
        "AQABAAAIBAABBAQAIfkEAQgAAQAsAAAAAAEAAQCBNrWhAAAAAAAAAAAACAQAAQQEADs="
    )
