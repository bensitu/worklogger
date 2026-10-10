"""Date-range context summaries with paged record drill-down."""

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QDateEdit, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout
from shiboken6 import isValid
from worklogger.domain.shared.result import Result
from worklogger.domain.shared.errors import InfrastructureError
from worklogger.domain.worklog.search import EntryFilter
from worklogger.infrastructure.i18n import _
from worklogger.presentation.date_labels import duration_label
from worklogger.presentation.errors import display_error_message
from worklogger.presentation.widgets.assets import apply_window_icon
from worklogger.presentation.widgets.icons import set_button_icon
from worklogger.presentation.widgets.record_search import RecordSearchDialog


class ProjectAnalyticsDialog(QDialog):
    records_changed = Signal()
    def __init__(self, analytics, records, day, parent=None, *, job_runner=None, selection_handler=None):
        super().__init__(parent)
        self._analytics, self._records = analytics, records
        self._runner, self._selection = job_runner, selection_handler
        self._version, self._job, self._range = 0, None, None
        self.setWindowTitle(_("Project statistics"))
        apply_window_icon(self)
        self.resize(900, 560)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        dates = QHBoxLayout()
        self.start_input, self.end_input = QDateEdit(), QDateEdit()
        for field, caption, value in ((self.start_input, _("From"), day.replace(day=1)), (self.end_input, _("To"), day)):
            field.setDisplayFormat("yyyy-MM-dd")
            field.setCalendarPopup(True)
            field.setDate(value)
            field.setAccessibleName(caption)
            label = QLabel(caption)
            label.setBuddy(field)
            dates.addWidget(label)
            dates.addWidget(field, 1)
        self.refresh_button = QPushButton(_("Apply"))
        set_button_icon(self.refresh_button, "check")
        dates.addWidget(self.refresh_button)
        root.addLayout(dates)
        self.results = QTreeWidget()
        self.results.setHeaderLabels([_("Project"), _("Work item"), _("Work hours"), _("Rest hours"), _("Leave hours"), _("Work days"), _("Records")])
        self.results.setRootIsDecorated(False)
        self.results.setUniformRowHeights(True)
        self.results.setColumnWidth(0, 160)
        self.results.setColumnWidth(1, 180)
        root.addWidget(self.results, 1)
        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        footer = QHBoxLayout()
        footer.addStretch()
        close = QPushButton(_("Close"))
        self.detail_button = QPushButton(_("View records"))
        set_button_icon(self.detail_button, "search")
        footer.addWidget(close)
        footer.addWidget(self.detail_button)
        root.addLayout(footer)
        for button in (close, self.detail_button, self.refresh_button):
            button.setAutoDefault(False)
        self.detail_button.setEnabled(False)
        close.clicked.connect(self.reject)
        self.refresh_button.clicked.connect(self._load)
        self.detail_button.clicked.connect(self._details)
        self.results.itemActivated.connect(lambda *_args: self._details())
        self.results.itemSelectionChanged.connect(lambda: self.detail_button.setEnabled(self._range is not None and self.results.currentItem() is not None))
        for field in (self.start_input, self.end_input):
            field.dateChanged.connect(self._invalidate)
        QTimer.singleShot(0, self._load)

    def _invalidate(self):
        self._version += 1
        self._range = None
        self.detail_button.setEnabled(False)

    def _load(self):
        self._invalidate()
        version = self._version
        start, end = self.start_input.date().toPython(), self.end_input.date().toPython()
        self.status_label.setText(_("Loading..."))
        if self._job is not None:
            self._job.cancel()
        def completed(result):
            if not isValid(self) or version != self._version:
                return
            self._job = None
            if not result.ok:
                self.status_label.setText(display_error_message(result.error))
                return
            self.results.clear()
            totals = [0.0, 0.0, 0.0]
            for group in result.value:
                context = group.context
                label = context.project_label or _("Unclassified")
                if context.project_label and context.project_id is None:
                    label += " (" + _("Unlinked") + ")"
                row = QTreeWidgetItem([label, context.work_item_label,
                    duration_label(group.work_hours), duration_label(group.rest_hours), duration_label(group.leave_hours),
                    str(group.work_days), str(group.record_count)])
                row.setData(0, Qt.ItemDataRole.UserRole, context)
                self.results.addTopLevelItem(row)
                for index, value in enumerate((group.work_hours, group.rest_hours, group.leave_hours)):
                    totals[index] += value
            self._range = (start, end)
            self.status_label.setText(_("Work: {work} | Rest: {rest} | Leave: {leave}").format(
                work=duration_label(totals[0]), rest=duration_label(totals[1]), leave=duration_label(totals[2])))
        operation = lambda: self._analytics.load_projects(start, end)
        if self._runner is None:
            completed(operation())
        else:
            try:
                self._job = self._runner.submit("project_analytics", lambda _token: operation(), on_complete=completed)
            except Exception:
                completed(Result.failure(InfrastructureError("analytics_load_failed", "analytics_load_failed")))

    def _details(self):
        row = self.results.currentItem()
        if self._range is None or row is None:
            return
        context = row.data(0, Qt.ItemDataRole.UserRole)
        criteria = EntryFilter(*self._range, project_id=context.project_id, work_item_id=context.work_item_id,
            unclassified=context.project_id is None,
            project_label=context.project_label if context.project_id is None else None,
            work_item_label=context.work_item_label if context.work_item_id is None else None)
        dialog = RecordSearchDialog(self._records, self._range[0], self, criteria=criteria,
                                   job_runner=self._runner, selection_handler=self._selection)
        dialog.entry_selected.connect(lambda _entry: self.accept())
        dialog.records_changed.connect(self.records_changed)
        dialog.records_changed.connect(self._load)
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()

    def done(self, result):
        self._invalidate()
        if self._job is not None:
            self._job.cancel()
        super().done(result)
