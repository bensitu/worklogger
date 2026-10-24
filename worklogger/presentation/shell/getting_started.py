"""First-use guidance lifecycle and account preference coordination."""

from PySide6.QtCore import QEvent, QObject, QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from worklogger.__about__ import GITHUB_URL
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.presentation.job_runner import owned_callback, shared_job_runner
from worklogger.presentation.widgets.getting_started import GettingStartedPanel


class GettingStartedController(QObject):
    def __init__(self, window, service, *, job_runner=None):
        super().__init__(window)
        self._window = window
        self._service = service
        self._runner = job_runner or shared_job_runner()
        self._loaded = False
        self._dismissed = False
        self._pending = False
        self._closed = False
        self.panel = GettingStartedPanel(window)
        self.panel.hide()
        window.getting_started_layout.insertWidget(0, self.panel)
        window.help_button.clicked.connect(self.open)
        self.panel.record_requested.connect(self._record)
        self.panel.dismiss_requested.connect(self.dismiss)
        self.panel.guide_requested.connect(self._open_guide)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(750)
        self._timer.timeout.connect(self._load)
        window.installEventFilter(self)
        window.entry_panel.busy_changed.connect(self._ready)

    def eventFilter(self, watched, event):
        if watched is self._window:
            if event.type() == QEvent.Type.Show and not self._loaded:
                self._timer.start()
            elif event.type() in (QEvent.Type.Hide, QEvent.Type.Close):
                self._timer.stop()
                self._closed = event.type() == QEvent.Type.Close
            if event.type() == QEvent.Type.Show:
                self._closed = False
        return False

    def _load(self):
        if self._loaded or not self._window.isVisible():
            return
        self._loaded = True
        def complete(result):
            if self._closed:
                return
            self._pending = result.ok and result.value is True
            self._ready()
        self._submit("load_getting_started", self._service.pending, complete)

    def _ready(self, _busy=False):
        if (self._pending and not self._dismissed and self._window.isVisible()
                and not self._window.entry_panel.is_busy):
            self.panel.show()
            self._ensure_visible()
            self._pending = False

    def open(self):
        if hasattr(self._window, "calendar_page") and not self._window._switch_route("calendar"):
            return
        self._dismissed = False
        self.panel.show()
        self._ensure_visible()

    def _ensure_visible(self):
        scroll = getattr(self._window, "records_scroll", None)
        if scroll is not None:
            QTimer.singleShot(0, self, lambda: scroll.ensureWidgetVisible(self.panel))

    def dismiss(self):
        self._dismissed = True
        self._pending = False
        self.panel.hide()
        def complete(result):
            if not result.ok and not self._closed:
                self._window._set_error(result.error)
        self._submit("dismiss_getting_started", self._service.dismiss, complete)

    def _submit(self, name, operation, complete):
        try:
            self._runner.submit(name, lambda _token: operation(), on_complete=owned_callback(self, complete))
        except Exception:
            complete(Result.failure(InfrastructureError("settings_save_failed" if name.startswith("dismiss")
                                                       else "settings_load_failed", "settings_operation_failed")))

    def _record(self):
        if self._window.new_record():
            self.dismiss()

    def _open_guide(self):
        QDesktopServices.openUrl(QUrl(GITHUB_URL + "/blob/main/docs/user-guide.md"))
