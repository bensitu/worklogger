"""Full-cover background surface that leaves foreground controls opaque."""

from PySide6.QtCore import QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from worklogger.domain.settings.background import BackgroundState
from worklogger.presentation.theme.background_player import BackgroundMoviePlayer


class MainBackgroundWidget(QWidget):
    active_changed = Signal(bool)
    frame_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("app_main_content_widget")
        self._base = QColor("#ffffff")
        self._state = BackgroundState()
        self._frame = QImage()
        self._version = 0
        self._player = None
        self._glass_colors = None
        self.setProperty("background_image", False)

    @property
    def background_active(self):
        return self._state.enabled and self._state.opacity > 0 and not self._frame.isNull()

    def set_base_color(self, color):
        value = QColor(color)
        if value == self._base:
            return
        self._base = value
        self.frame_changed.emit()
        self.update()

    def set_glass_colors(self, colors):
        value = colors if colors.material == "glass" else None
        if value == self._glass_colors:
            return
        self._glass_colors = value
        self.frame_changed.emit()
        self.update()

    def backdrop(self, rect, size):
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(self._base)
        painter = QPainter(image)
        painter.scale(size.width() / rect.width(), size.height() / rect.height())
        painter.translate(-rect.x(), -rect.y())
        self._paint_background(painter)
        painter.end()
        return image

    def set_background(self, state, frame):
        self._version += 1
        self._state, self._frame = state, frame
        if state.enabled and state.image is not None and state.image.animated:
            if self._player is None:
                self._player = BackgroundMoviePlayer(self)
                self._player.frame_ready.connect(self._set_frame)
                self._player.failed.connect(self._animation_failed)
            self._player.set_source(state.image, self._version)
        elif self._player is not None:
            self._player.set_source(None, self._version)
        self._update_playback()
        self._update_active()
        self.frame_changed.emit()
        self.update()

    def _set_frame(self, version, frame):
        if version == self._version and self._state.enabled:
            self._frame = frame
            self.frame_changed.emit()
            self.update()

    def _animation_failed(self, version):
        if version == self._version:
            self._version += 1
            self._frame = QImage()
            self._update_playback()
            self._update_active()
            self.frame_changed.emit()
            self.update()

    def _update_active(self):
        active = self.background_active
        if self.property("background_image") != active:
            self.setProperty("background_image", active)
            self.active_changed.emit(active)

    def _update_playback(self):
        if self._player is not None:
            self._player.set_playing(self.isVisible() and self.background_active)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_playback()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._update_playback()

    def shutdown(self):
        if self._player is not None:
            self._player.shutdown()
            self._player.deleteLater()
            self._player = None

    def paintEvent(self, event):
        painter = QPainter(self)
        self._paint_background(painter)

    def _paint_background(self, painter):
        painter.fillRect(self.rect(), self._base)
        if self._glass_colors is not None:
            colors = ("#26333b", "#343c43", "#24413f") if self._glass_colors.dark else ("#d0e0eb", "#eff2f5", "#d3e7df")
            gradient = QLinearGradient(QPointF(), QPointF(max(1, self.width()), max(1, self.height())))
            for position, color in zip((0.0, 0.5, 1.0), colors):
                gradient.setColorAt(position, QColor(color))
            painter.fillRect(QRectF(-self.width(), -self.height(), self.width() * 3, self.height() * 3), gradient)
        if not self.background_active:
            return
        scale = max(self.width() / self._frame.width(), self.height() / self._frame.height())
        width, height = self.width() / scale, self.height() / scale
        source = QRectF((self._frame.width() - width) / 2, (self._frame.height() - height) / 2, width, height)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setOpacity(self._state.opacity / 100)
        painter.drawImage(QRectF(self.rect()), self._frame, source)
