"""First-use guidance lifecycle and account preference coordination."""

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog

from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import owned_callback, shared_job_runner
from worklogger.presentation.help import open_user_guide
from worklogger.presentation.widgets.getting_started import GettingStartedDialog


class GettingStartedController(QObject):
    def __init__(self, window, service, *, job_runner=None):
        super().__init__(window)
        self._window = window
        self._service = service
        self._runner = job_runner or shared_job_runner()
        self._loaded = False
        self._dismissed = False
        self._pending = False
        self.dialog = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(750)
        self._timer.timeout.connect(self._check)
        window.installEventFilter(self)
        window.entry_panel.busy_changed.connect(self._ready)
        window.entry_panel.dirty_changed.connect(self._ready)

    def _check(self):
        self._ready() if self._loaded else self._load()

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() in (QEvent.Type.Show, QEvent.Type.WindowStateChange) and not self._window.isMinimized():
                if not self._loaded:
                    self._timer.start()
                else:
                    QTimer.singleShot(0, self, self._ready)
            elif event.type() == QEvent.Type.Hide:
                self._timer.stop()
                if self.dialog is not None:
                    self.dialog.hide()
        return False

    def _load(self):
        if self._loaded or not self._window.isVisible() or self._window.isMinimized():
            return
        self._loaded = True
        def complete(result):
            self._pending = result.ok and result.value is True
            self._ready()
        self._submit("load_getting_started", self._service.pending, complete, error_code="settings_load_failed")

    def _ready(self, _busy=False):
        if not self._window.isVisible() or self._window.isMinimized():
            return
        if self.dialog is not None:
            if not self.dialog.isVisible() and QApplication.activeModalWidget() is None:
                self.dialog.show()
            return
        if not self._pending or self._dismissed:
            return
        panel = self._window.entry_panel
        model = panel.view_model
        calendar = getattr(self._window, "calendar_page", None)
        if (panel.is_busy or panel.is_dirty or model.timer is not None or model.restore_failed
                or panel.is_processing_text or QApplication.activeModalWidget() is not None
                or calendar is not None and self._window.page_stack.currentWidget() is not calendar):
            self._timer.start()
            return
        self._show()

    def open(self):
        if (not self._window.isVisible() or self._window.isMinimized()
                or self._window.entry_panel.is_busy or self._window.entry_panel.is_processing_text):
            return
        if self.dialog is not None:
            self.dialog.show()
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if QApplication.activeModalWidget() is not None:
            return
        if hasattr(self._window, "calendar_page") and not self._window._switch_route("calendar"):
            return
        self._show()

    def _show(self):
        self._timer.stop()
        target = getattr(getattr(self._window, "calendar_page", None), "right_panel", self._window.entry_panel)
        dialog = GettingStartedDialog(target, self._window)
        self.dialog = dialog
        dialog.guide_requested.connect(open_user_guide)
        dialog.finished.connect(self._finished)
        dialog.open()

    def _finished(self, code):
        dialog, self.dialog = self.dialog, None
        dialog.deleteLater()
        self._dismissed = True
        self._pending = False
        def complete(result):
            if not result.ok and self._window.isVisible():
                self._window._set_error(result.error)
        self._submit("dismiss_getting_started", self._service.dismiss, complete, error_code="settings_save_failed")
        if code == QDialog.DialogCode.Accepted:
            QTimer.singleShot(0, self, self._focus_recording)

    def _focus_recording(self):
        if not self._window.isVisible() or QApplication.activeModalWidget() is not None:
            return
        panel = self._window.entry_panel
        target = panel.start_input if panel.time_tabs.currentIndex() == 0 else panel.clock_in_button
        if not target.isEnabled():
            target = panel.content_input
        self._window.activateWindow()
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _submit(self, name, operation, complete, *, error_code):
        try:
            self._runner.submit(name, lambda _token: operation(), on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError(error_code, error_code)))
