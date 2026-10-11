"""Bounded, worker-safe glass rendering from application-owned image data."""

from functools import lru_cache
from math import sqrt

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter

GLASS_PADDING = 18
MAX_GLASS_PIXELS = 60_000


def render_geometry(width, height):
    if width < 2 or height < 2:
        raise ValueError("glass_backdrop_invalid")
    scale = min(1.0, sqrt(MAX_GLASS_PIXELS / (width * height)), 720 / max(width, height))
    return max(2, int(width * scale)), max(2, int(height * scale)), scale, int(GLASS_PADDING * scale)


@lru_cache(maxsize=4)
def _kernel(width, height, scale):
    from worklogger._vendor.pyglass.refract import GlassMaterial
    material = GlassMaterial(thickness=0.4, frost=0.6, strength=10, bevel=12, pad=GLASS_PADDING,
                             ior_edge=1.8, ior_inner=1.45, chroma=0.025, disp_glow=15,
                             disp_width=1.5, reflect=0.25, max_frost_sigma=5)
    return material.build_kernel(width, height, min(8 * scale, width / 2, height / 2), scale)


def render_glass(backdrop: QImage, width: int, height: int, tint: str) -> QImage:
    from worklogger._vendor.pyglass.refract import array_to_qimage, qimage_to_array
    if backdrop.isNull():
        raise ValueError("glass_backdrop_invalid")
    output_width, output_height, scale, pad = render_geometry(width, height)
    sample = backdrop.scaled(output_width + 2 * pad, output_height + 2 * pad,
                             Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    result = array_to_qimage(_kernel(output_width, output_height, scale).apply(qimage_to_array(sample)))
    color = QColor(tint)
    if not color.isValid():
        raise ValueError("glass_tint_invalid")
    color.setAlpha(190 if color.lightness() < 128 else 160)
    painter = QPainter(result)
    painter.fillRect(result.rect(), color)
    painter.end()
    return result
