"""Application icon loader — checks assets/ folder, then falls back to programmatic icon."""

import sys
import os
from PySide6.QtGui import (QIcon, QPixmap, QPainter, QColor, QPen,
                           QBrush, QLinearGradient)
from PySide6.QtCore import QRectF, QPointF, Qt


def _assets_dir() -> str:
    """Return the assets/ directory path (works packed and unpacked)."""
    if getattr(sys, "frozen", False):
        # PyInstaller: sys._MEIPASS has bundled files; fallback to exe dir
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        # utils/icon.py → utils/ → worklogger/ (project root)
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets")


def make_icon() -> QIcon:
    """Load the platform-appropriate icon from assets/, or draw a fallback."""
    assets = _assets_dir()

    # Platform-specific candidates first, then generic ico
    if sys.platform == "darwin":
        candidates = ["worklogger.icns", "worklogger.ico", "workLogger.ico"]
    else:
        candidates = ["worklogger.ico", "workLogger.ico"]

    # Also search root-level locations used by older packaging layouts.
    legacy_dirs = []
    if getattr(sys, "frozen", False):
        legacy_dirs = [os.path.dirname(sys.executable)]
    else:
        legacy_dirs = [os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))]

    # Also try _MEIPASS root directly when assets/ was not bundled.
    extra_dirs = []
    if getattr(sys, "frozen", False):
        extra_dirs = [getattr(sys, "_MEIPASS", "")]
    for directory in [assets] + legacy_dirs + extra_dirs:
        if not directory:
            continue
        for name in candidates:
            path = os.path.join(directory, name)
            if os.path.isfile(path):
                icon = QIcon(path)
                if not icon.isNull():
                    return icon

    # Programmatic fallback
    icon = QIcon()
    for sz in [16, 24, 32, 48, 64, 128, 256]:
        icon.addPixmap(_draw(sz))
    return icon


def _draw(sz: int) -> QPixmap:
    px = QPixmap(sz, sz)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    s = sz / 64

    def sc(v): return v * s

    grad = QLinearGradient(0, 0, 0, sz)
    grad.setColorAt(0.0, QColor("#5a9ff5"))
    grad.setColorAt(1.0, QColor("#3570c8"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(sc(3), sc(4), sc(56), sc(55)), sc(10), sc(10))

    p.setBrush(QBrush(QColor("#1e4fa0")))
    p.drawRoundedRect(QRectF(sc(3), sc(4), sc(56), sc(20)), sc(10), sc(10))
    p.drawRect(QRectF(sc(3), sc(14), sc(56), sc(10)))

    p.setBrush(QBrush(QColor("#ffffff")))
    p.setPen(QPen(QColor("#1e4fa0"), max(1, sc(2))))
    for rx in [20, 44]:
        p.drawEllipse(QRectF(sc(rx - 4), sc(0), sc(8), sc(8)))

    p.setBrush(QBrush(QColor("#eef3ff")))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(sc(8), sc(22), sc(46), sc(32)), sc(5), sc(5))

    p.setBrush(QBrush(QColor("#a0b8e0")))
    for gx in [16, 24, 32, 40, 48]:
        for gy in [30, 38, 46]:
            r = sc(1.8)
            p.drawEllipse(QRectF(sc(gx) - r, sc(gy) - r, r * 2, r * 2))

    pen = QPen(QColor("#4f8ef7"), max(2, sc(4.5)),
               Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.drawLine(QPointF(sc(22), sc(40)), QPointF(sc(29), sc(48)))
    p.drawLine(QPointF(sc(29), sc(48)), QPointF(sc(44), sc(30)))
    p.end()
    return px
