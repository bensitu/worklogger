"""Desktop reporting dependency composition."""

from __future__ import annotations

from worklogger.app.use_cases.analytics import (
    GetAnalyticsBundleHandler,
    GetAnalyticsDashboardHandler,
)
from worklogger.app.use_cases.notes import DailyNotesService
from worklogger.app.use_cases.reports import (
    DeleteReportHandler,
    GenerateReportHandler,
    GetReportForPeriodHandler,
    ListReportsHandler,
    SaveReportHandler,
)
from worklogger.composition.context import RuntimeHandlers, RuntimeRepositories
from worklogger.domain.auth.models import User
from worklogger.infrastructure.export import (
    AnalyticsCsvExporter,
    AnalyticsPdfExporter,
)
from worklogger.infrastructure.i18n import _, get_language
from worklogger.presentation.analytics import AnalyticsWorkflowController
from worklogger.presentation.notes import NotesWorkflowController
from worklogger.presentation.reporting import ReportsWorkflowController
from worklogger.presentation.viewmodels import (
    AnalyticsViewModel,
    NoteEditorViewModel,
    ReportEditorViewModel,
)


def _build_analytics_workflow(
    user: User,
    repositories: RuntimeRepositories,
) -> AnalyticsWorkflowController:
    return AnalyticsWorkflowController(
        AnalyticsViewModel(
            user_id=user.id,
            bundle_handler=GetAnalyticsBundleHandler(repositories.work_logs),
            dashboard_handler=GetAnalyticsDashboardHandler(
                repositories.work_logs, repositories.settings
            ),
            csv_exporter=AnalyticsCsvExporter(),
            pdf_exporter=AnalyticsPdfExporter(),
        )
    )


def _build_notes_workflow(
    user: User,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
    job_runner=None,
) -> NotesWorkflowController:
    return NotesWorkflowController(
        NoteEditorViewModel(
            DailyNotesService(
                user_id=user.id,
                notes=repositories.daily_notes,
                settings=repositories.settings,
                previous_entries=repositories.quick_logs,
            ),
            language=get_language(),
            markdown_exporter=handlers.markdown_exporter,
            rewrite_handler=handlers.rewrite_handler,
        ),
        job_runner=job_runner,
    )


def _build_reports_workflow(
    user: User,
    repositories: RuntimeRepositories,
    handlers: RuntimeHandlers,
) -> ReportsWorkflowController:
    return ReportsWorkflowController(
        ReportEditorViewModel(
            user_id=user.id,
            language=get_language(),
            generate_handler=GenerateReportHandler(
                work_logs=repositories.work_logs,
                quick_logs=repositories.quick_logs,
                calendar_events=repositories.calendar_events,
                templates=handlers.templates,
                notes=repositories.daily_notes,
                translator=_,
                note_settings=repositories.settings,
                profiles=handlers.user_profiles,
            ),
            get_report_handler=GetReportForPeriodHandler(repositories.reports),
            list_reports_handler=ListReportsHandler(repositories.reports),
            delete_report_handler=DeleteReportHandler(repositories.reports),
            templates=handlers.templates,
            save_report_handler=SaveReportHandler(repositories.reports),
            save_template_handler=handlers.save_template_handler,
            reset_template_handler=handlers.reset_template_handler,
            markdown_exporter=handlers.markdown_exporter,
            rewrite_handler=handlers.rewrite_handler,
        )
    )
