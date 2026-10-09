"""Circular avatar rendering and a bounded drag-and-zoom crop editor."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from worklogger.infrastructure.i18n import _
from worklogger.infrastructure.images.avatar import decode_avatar, encode_avatar
from worklogger.presentation.widgets.assets import apply_window_icon, pixmap_asset


def round_avatar(source, size):
    scaled = source.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addEllipse(0, 0, size, size)
    painter.setClipPath(clip)
    painter.drawPixmap(
        (size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled
    )
    painter.end()
    return result


def avatar_pixmap(encoded="", size=72):
    image = decode_avatar(encoded)
    source = (
        QPixmap.fromImage(image)
        if image is not None
        else pixmap_asset("images/avatar.webp")
    )
    return round_avatar(source, size)


class AvatarCropCanvas(QWidget):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.image = image
        self.setFixedSize(280, 280)
        self._zoom = 1.0
        self._center = QPointF(image.width() / 2, image.height() / 2)
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(_("Avatar crop"))

    def _rect(self):
        side = min(self.image.width(), self.image.height()) / self._zoom
        half = side / 2
        self._center.setX(max(half, min(self.image.width() - half, self._center.x())))
        self._center.setY(max(half, min(self.image.height() - half, self._center.y())))
        return QRectF(self._center.x() - half, self._center.y() - half, side, side)

    def set_zoom(self, value):
        self._zoom = max(1.0, min(3.0, value / 100))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        clip = QPainterPath()
        clip.addEllipse(QRectF(self.rect()))
        painter.setClipPath(clip)
        painter.drawImage(QRectF(self.rect()), self.image, self._rect())
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            scale = self._rect().width() / self.width()
            self._center -= (event.position() - self._drag) * scale
            self._drag = event.position()
            self.update()

    def mouseReleaseEvent(self, event):
        self._drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def encoded_avatar(self):
        return encode_avatar(self.image.copy(self._rect().toAlignedRect()))

    def keyPressEvent(self, event):
        offsets = {
            Qt.Key.Key_Left: QPointF(-1, 0),
            Qt.Key.Key_Right: QPointF(1, 0),
            Qt.Key.Key_Up: QPointF(0, -1),
            Qt.Key.Key_Down: QPointF(0, 1),
        }
        if event.key() in offsets:
            self._center += offsets[event.key()] * (self._rect().width() / 28)
            self.update()
            event.accept()
        else:
            super().keyPressEvent(event)


class AvatarCropDialog(QDialog):
    def __init__(self, image, parent=None):
        super().__init__(parent)
        self.setObjectName("avatar_crop_dialog")
        self.setWindowTitle(_("Change avatar"))
        apply_window_icon(self)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        self.canvas = AvatarCropCanvas(image, self)
        root.addWidget(self.canvas, 0, Qt.AlignmentFlag.AlignCenter)
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(100, 300)
        self.zoom_slider.setAccessibleName(_("Zoom"))
        self.zoom_slider.valueChanged.connect(self.canvas.set_zoom)
        root.addWidget(QLabel(_("Zoom")))
        root.addWidget(self.zoom_slider)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton(_("Cancel"))
        cancel.clicked.connect(self.reject)
        self.save_button = QPushButton(_("Save"))
        self.save_button.setProperty("variant", "primary")
        self.save_button.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.save_button)
        root.addLayout(buttons)
