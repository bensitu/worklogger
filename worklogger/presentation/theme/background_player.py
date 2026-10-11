"""Worker-thread animation playback with a bounded latest-frame mailbox."""

from threading import Lock

from PySide6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QObject,
    QThread,
    Signal,
    Slot,
)
from PySide6.QtGui import QImage, QImageReader, QMovie


class _FrameMailbox:
    def __init__(self):
        self._lock = Lock()
        self._frame = None
        self._pending = False

    def offer(self, version, frame):
        with self._lock:
            self._frame = (version, frame)
            notify = not self._pending
            self._pending = True
            return notify

    def take(self):
        with self._lock:
            frame, self._frame = self._frame, None
            self._pending = False
            return frame


class _MovieWorker(QObject):
    frame_available = Signal()
    failed = Signal(int)

    def __init__(self, mailbox):
        super().__init__()
        self._mailbox = mailbox
        self._movie = self._buffer = None
        self._version = 0
        self._playing = False

    @Slot(object, int)
    def set_source(self, image, version):
        if self._movie is not None:
            self._movie.stop()
            self._movie.frameChanged.disconnect()
            self._movie.error.disconnect()
            self._movie.deleteLater()
            self._buffer.deleteLater()
        self._movie = self._buffer = None
        self._version = version
        if image is None:
            return
        self._buffer = QBuffer(self)
        self._buffer.setData(QByteArray(image.data))
        self._buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._movie = QMovie(self._buffer, QByteArray(image.format.encode("ascii")), self)
        self._movie.setCacheMode(QMovie.CacheMode.CacheNone)
        self._movie.frameChanged.connect(self._publish_frame)
        self._movie.error.connect(self._failed)
        if not self._movie.isValid() or not self._movie.jumpToFrame(0):
            self.failed.emit(version)
            return
        if self._playing:
            self._movie.start()

    @Slot(bool)
    def set_playing(self, playing):
        self._playing = playing
        if self._movie is None:
            return
        if playing:
            if self._movie.state() == QMovie.MovieState.NotRunning:
                self._movie.start()
            else:
                self._movie.setPaused(False)
        else:
            self._movie.setPaused(True)

    @Slot(int)
    def _publish_frame(self, _number):
        if self._mailbox.offer(self._version, self._movie.currentImage()):
            self.frame_available.emit()

    @Slot()
    def _failed(self):
        # Qt's WebP reader may report UnknownError when rewinding a valid loop.
        if (self._movie.lastError() == QImageReader.ImageReaderError.UnknownError
                and self._movie.state() == QMovie.MovieState.Running):
            return
        self._movie.stop()
        self.failed.emit(self._version)


class BackgroundMoviePlayer(QObject):
    frame_ready = Signal(int, QImage)
    failed = Signal(int)
    source_requested = Signal(object, int)
    playing_requested = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playing = False
        self._closed = False
        self._version = None
        self._mailbox = _FrameMailbox()
        self._thread = QThread(self)
        self._worker = _MovieWorker(self._mailbox)
        self._worker.moveToThread(self._thread)
        self.source_requested.connect(self._worker.set_source)
        self.playing_requested.connect(self._worker.set_playing)
        self._worker.frame_available.connect(self._take_frame)
        self._worker.failed.connect(self.failed)
        self._thread.finished.connect(self._worker.deleteLater)
        # Join before QObject ownership destroys the running QThread.
        thread = self._thread
        self.destroyed.connect(lambda: _join_thread(thread))
        self._thread.start()

    @Slot()
    def _take_frame(self):
        frame = self._mailbox.take()
        if not self._closed and self._playing and frame is not None and frame[0] == self._version:
            self.frame_ready.emit(*frame)

    def set_source(self, image, version):
        if self._closed:
            return
        self._version = version
        self._mailbox.take()
        self.source_requested.emit(image, version)

    def set_playing(self, playing):
        if self._closed:
            return
        # Stop delivery immediately, even while the worker processes queued frames.
        self._playing = bool(playing)
        if not self._playing:
            self._mailbox.take()
        self.playing_requested.emit(self._playing)

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self._playing = False
        _join_thread(self._thread)
        self._mailbox.take()


def _join_thread(thread):
    thread.quit()
    thread.wait()
