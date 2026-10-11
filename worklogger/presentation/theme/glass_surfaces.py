"""Glass panel backgrounds with coalesced updates and owned render jobs."""

from collections import OrderedDict

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QRectF, QSize, QTimer, Qt, QObject, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtWidgets import QFrame, QScrollArea, QWidget
from shiboken6 import isValid

from worklogger.presentation.job_runner import QtJobRunner
from worklogger.presentation.theme.glass_renderer import GLASS_PADDING, render_geometry, render_glass
from worklogger.presentation.theme.native_glass import NativeGlassAdapter
from worklogger.presentation.widgets._style import set_style_property

_SURFACE_NAMES = {"app_main_content_widget", "app_sidebar_frame",
                  "settings_navigation_frame", "worklog_entry_panel_widget"}


class GlassLayer(QWidget):
    def __init__(self, target, colors):
        super().__init__(target)
        self.setObjectName("glass_surface_layer_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.image = QImage()
        self.colors = colors
        self.version = 0
        self.setGeometry(target.rect())
        self.lower()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 7, 7)
        painter.setClipPath(path)
        painter.fillRect(rect, QColor(self.colors.surface))
        if not self.image.isNull():
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(rect, self.image)


class GlassThemeController(QObject):
    def __init__(self, window, source, *, job_runner=None, native_target=None):
        super().__init__(window)
        self._window, self._source, self._runner = window, source, job_runner
        self._native = NativeGlassAdapter(native_target) if native_target is not None else None
        self._layers, self._jobs, self._pending = {}, {}, OrderedDict()
        self._scrollbars = set()
        self._windows = {window}
        self._enabled, self._disposed, self._generation, self._next_job = False, False, 0, 0
        self._colors = None
        self._software_failed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._dispatch)
        source.frame_changed.connect(self._queue_all)
        window.installEventFilter(self)
        window.destroyed.connect(self.dispose)

    @property
    def is_rendering(self):
        return bool(self._jobs or self._pending or self._timer.isActive())

    def configure(self, colors):
        if self._disposed or colors == self._colors:
            return
        self._generation += 1
        self._enabled, self._colors = colors.theme == "liquid_glass", colors
        self._software_failed = False
        self._timer.stop()
        self._pending.clear()
        for handle in self._jobs.values():
            if handle is not None:
                handle.cancel()
        self._source.set_glass_colors(colors)
        if not self._enabled and self._native is not None:
            self._native.remove()
        for target, layer in tuple(self._layers.items()):
            if not isValid(target):
                del self._layers[target]
                continue
            layer.colors, layer.image = colors, QImage()
            layer.setVisible(self._enabled)
            layer.update()
            set_style_property(target, "glass_surface", self._enabled)
        self.refresh_surfaces()

    def refresh_surfaces(self):
        if not self._enabled or self._disposed or self._software_failed:
            return
        for target in self._window.findChildren(QWidget):
            if target.property("glass_surface_eligible") is False:
                continue
            if (isinstance(target, QFrame) and target.property("card")) or target.objectName() in _SURFACE_NAMES:
                if target not in self._layers:
                    layer = GlassLayer(target, self._colors)
                    self._layers[target] = layer
                    target.installEventFilter(self)
                    target.destroyed.connect(lambda _object=None, target=target: self._forget_target(target))
                    set_style_property(target, "glass_surface", True)
                    layer.show()
                    owner = target.window()
                    if owner not in self._windows:
                        self._windows.add(owner)
                        owner.installEventFilter(self)
                        owner.destroyed.connect(lambda _object=None, owner=owner: self._windows.discard(owner))
        for scroll in self._window.findChildren(QScrollArea):
            bar = scroll.verticalScrollBar()
            if bar not in self._scrollbars:
                self._scrollbars.add(bar)
                bar.valueChanged.connect(self._queue_all)
                bar.destroyed.connect(lambda _object=None, bar=bar: self._scrollbars.discard(bar))
        self._queue_all()

    def _forget_target(self, target):
        layer = self._layers.pop(target, None)
        if layer is not None:
            self._pending.pop(layer, None)

    def _schedule(self, delay=90):
        if self._pending and (not self._timer.isActive() or delay == 0):
            self._timer.start(delay)

    @Slot()
    def _queue_all(self):
        if not self._enabled or self._disposed or self._software_failed:
            return
        for target, layer in self._layers.items():
            if isValid(target) and target.isVisible() and not target.visibleRegion().isEmpty():
                self._pending.setdefault(layer, None)
        self._schedule()

    def eventFilter(self, watched, event):
        if not self._enabled or self._disposed or self._software_failed:
            return False
        if watched in self._windows:
            if watched is self._window and event.type() == QEvent.Type.Hide and self._native is not None:
                self._native.remove()
            elif event.type() in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.Move):
                self._queue_all()
        elif watched in self._layers:
            layer = self._layers[watched]
            if event.type() in (QEvent.Type.Show, QEvent.Type.Move, QEvent.Type.Resize):
                layer.version += 1
                layer.setGeometry(watched.rect())
                if watched.isVisible():
                    self._pending.setdefault(layer, None)
                    self._schedule()
            elif event.type() == QEvent.Type.Hide:
                layer.version += 1
                self._pending.pop(layer, None)
        return False

    @Slot()
    def _dispatch(self):
        if not self._enabled or self._disposed or self._software_failed:
            return
        if self._native is not None and self._window.isVisible():
            self._native.apply(dark=self._colors.dark)
        if self._runner is None:
            self._runner = QtJobRunner(QCoreApplication.instance())
        while self._pending and len(self._jobs) < 2:
            layer, _value = self._pending.popitem(last=False)
            if not isValid(layer):
                continue
            target = layer.parentWidget()
            if not target.isVisible() or target.visibleRegion().isEmpty() or target.width() < 2 or target.height() < 2:
                continue
            if self._native is not None and self._native.active and target is self._native.target:
                layer.hide()
                continue
            layer.show()
            width, height = target.width(), target.height()
            sample_width, sample_height, _scale, pad = render_geometry(width, height)
            origin = target.mapToGlobal(QPoint()) - self._source.mapToGlobal(QPoint())
            rect = target.rect().translated(origin).adjusted(-GLASS_PADDING, -GLASS_PADDING, GLASS_PADDING, GLASS_PADDING)
            backdrop = self._source.backdrop(rect, QSize(sample_width + 2 * pad, sample_height + 2 * pad))
            generation, version, tint = self._generation, layer.version, self._colors.surface
            self._next_job += 1
            key = self._next_job
            self._jobs[key] = None

            def complete(result, layer=layer, key=key, generation=generation, version=version):
                if not isValid(self) or self._disposed:
                    return
                self._jobs.pop(key, None)
                if self._enabled and generation == self._generation and isValid(layer) and version == layer.version and result.ok:
                    layer.image = result.value
                    layer.update()
                elif (generation == self._generation and not result.ok
                      and getattr(result.error, "code", "") != "job_cancelled"):
                    self._software_failed = True
                    self._pending.clear()
                self._schedule(0)

            try:
                handle = self._runner.submit("glass_background", lambda _token, image=backdrop, w=width, h=height, tint=tint:
                                             render_glass(image, w, h, tint), on_complete=complete)
                if key in self._jobs:
                    self._jobs[key] = handle
            except RuntimeError:
                self._jobs.pop(key, None)
                self._software_failed = True
                self._pending.clear()

    @Slot()
    def dispose(self):
        if getattr(self, "_disposed", True):
            return
        self._disposed = True
        self._timer.stop()
        for handle in self._jobs.values():
            if handle is not None:
                handle.cancel()
        self._jobs.clear()
        self._pending.clear()
        if self._native is not None:
            self._native.remove()
