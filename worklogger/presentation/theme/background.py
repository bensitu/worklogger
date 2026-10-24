"""Full-cover background surface that leaves foreground controls opaque."""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from worklogger.domain.settings.background import BackgroundState
from worklogger.presentation.theme.background_player import BackgroundMoviePlayer
from worklogger.presentation.theme.materials import material_profile


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
        self._material_colors = None
        application = QGuiApplication.instance()
        self._application_active = application.applicationState() == Qt.ApplicationState.ApplicationActive
        application.applicationStateChanged.connect(self._application_state_changed)
        self.setProperty("background_image", False)

    @property
    def background_active(self):
        return self._state.enabled and self._state.opacity > 0 and not self._frame.isNull()

    @property
    def animation_active(self):
        return self.background_active and self._state.image is not None and self._state.image.animated

    def set_base_color(self, color):
        value = QColor(color)
        if value == self._base:
            return
        self._base = value
        self.frame_changed.emit()
        self.update()

    def set_material_colors(self, colors):
        value = colors if material_profile(colors.material).backdrop(colors.dark) else None
        if value == self._material_colors:
            return
        self._material_colors = value
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
        if state.image == self._state.image and state.enabled == self._state.enabled and not self._frame.isNull():
            self._state = state
            self._update_playback()
            self._update_active()
            self.frame_changed.emit()
            self.update()
            return
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
            self._player.set_playing(self._application_active and self.isVisible() and self.background_active)

    def _application_state_changed(self, state):
        self._application_active = state == Qt.ApplicationState.ApplicationActive
        self._update_playback()

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
        if self._material_colors is not None:
            colors = material_profile(self._material_colors.material).backdrop(self._material_colors.dark)
            gradient = QLinearGradient(QPointF(), QPointF(max(1, self.width()), max(1, self.height())))
            for index, color in enumerate(colors):
                position = index / max(1, len(colors) - 1)
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
