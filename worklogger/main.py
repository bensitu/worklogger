"""Entry point for the WorkLogger desktop application."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

if __package__ in {None, ""}:
    workspace_root = str(Path(__file__).resolve().parents[1])
    if workspace_root not in sys.path:
        sys.path.insert(0, workspace_root)

from worklogger.infrastructure.i18n import _

DesktopRunner = Callable[[Sequence[str]], int]

SMOKE_IMPORT_MODULES = (
    "worklogger.__about__",
    "worklogger.bootstrap",
    "worklogger.app.container",
    "worklogger.app.commands.ai_commands",
    "worklogger.app.commands.calendar_commands",
    "worklogger.app.commands.data_portability_commands",
    "worklogger.app.commands.identity_commands",
    "worklogger.app.commands.local_model_commands",
    "worklogger.app.commands.note_commands",
    "worklogger.app.event_bus",
    "worklogger.app.job_runner",
    "worklogger.app.ports",
    "worklogger.app.queries.ai_queries",
    "worklogger.app.queries.auth_queries",
    "worklogger.app.queries.identity_queries",
    "worklogger.app.queries.local_model_queries",
    "worklogger.app.queries.note_queries",
    "worklogger.app.queries.report_queries",
    "worklogger.app.queries.update_queries",
    "worklogger.app.use_cases.ai",
    "worklogger.app.use_cases.analytics",
    "worklogger.app.use_cases.auth",
    "worklogger.app.use_cases.calendar",
    "worklogger.app.use_cases.data_portability",
    "worklogger.app.use_cases.identity",
    "worklogger.app.use_cases.local_models",
    "worklogger.app.use_cases.notes",
    "worklogger.app.use_cases.quick_logs",
    "worklogger.app.use_cases.reports",
    "worklogger.app.use_cases.settings",
    "worklogger.app.use_cases.updates",
    "worklogger.app.use_cases.work_logs",
    "worklogger.config.feature_flags",
    "worklogger.domain.analytics.rules",
    "worklogger.domain.auth.policies",
    "worklogger.domain.identity.models",
    "worklogger.domain.local_model.models",
    "worklogger.domain.notes.models",
    "worklogger.domain.quicklog.rules",
    "worklogger.domain.reporting.periods",
    "worklogger.domain.reporting.templates",
    "worklogger.infrastructure.i18n",
    "worklogger.domain.shared.result",
    "worklogger.domain.worklog.rules",
    "worklogger.domain.worklog.repositories",
    "worklogger.infrastructure.backup.sqlite_backup",
    "worklogger.infrastructure.calendar",
    "worklogger.infrastructure.calendar.holidays_provider",
    "worklogger.infrastructure.calendar.ics_import",
    "worklogger.infrastructure.database.connection",
    "worklogger.infrastructure.database.migrations.runner",
    "worklogger.infrastructure.database.paths",
    "worklogger.infrastructure.database.unit_of_work",
    "worklogger.infrastructure.export.worklog_csv",
    "worklogger.infrastructure.export.worklog_csv_import",
    "worklogger.infrastructure.export.worklog_ics",
    "worklogger.infrastructure.export.markdown",
    "worklogger.infrastructure.export.analytics",
    "worklogger.infrastructure.repositories.auth_sqlite",
    "worklogger.infrastructure.repositories.audit_sqlite",
    "worklogger.infrastructure.repositories.calendar_sqlite",
    "worklogger.infrastructure.repositories.note_sqlite",
    "worklogger.infrastructure.repositories.quicklog_sqlite",
    "worklogger.infrastructure.repositories.report_sqlite",
    "worklogger.infrastructure.repositories.settings_sqlite",
    "worklogger.infrastructure.repositories.template_sqlite",
    "worklogger.infrastructure.repositories.worklog_sqlite",
    "worklogger.infrastructure.security.key_store",
    "worklogger.infrastructure.security.session_store",
    "worklogger.infrastructure.security.password_hasher",
    "worklogger.infrastructure.templates",
    "worklogger.infrastructure.templates.builtin",
    "worklogger.infrastructure.templates.custom",
    "worklogger.infrastructure.update",
    "worklogger.infrastructure",
    "worklogger.infrastructure.ai",
    "worklogger.infrastructure.ai.external",
    "worklogger.infrastructure.ai.local",
    "worklogger.infrastructure.ai.router",
    "worklogger.infrastructure.identity",
    "worklogger.infrastructure.identity.config",
    "worklogger.infrastructure.identity.oidc",
    "worklogger.infrastructure.identity.pkce",
    "worklogger.infrastructure.identity.providers",
    "worklogger.infrastructure.local_model",
    "worklogger.infrastructure.local_model.store",
    "worklogger.infrastructure.logging",
    "worklogger.presentation.ai",
    "worklogger.presentation.ai.controller",
    "worklogger.presentation.ai.dialog",
    "worklogger.presentation.analytics",
    "worklogger.presentation.analytics.controller",
    "worklogger.presentation.analytics.dialog",
    "worklogger.presentation.errors",
    "worklogger.presentation.identity",
    "worklogger.presentation.identity.controller",
    "worklogger.presentation.identity.dialog",
    "worklogger.presentation.job_runner",
    "worklogger.presentation.local_models",
    "worklogger.presentation.local_models.controller",
    "worklogger.presentation.local_models.dialog",
    "worklogger.presentation.notes",
    "worklogger.presentation.notes.controller",
    "worklogger.presentation.notes.dialog",
    "worklogger.presentation.quick_logs",
    "worklogger.presentation.quick_logs.controller",
    "worklogger.presentation.quick_logs.dialog",
    "worklogger.presentation.reporting",
    "worklogger.presentation.reporting.controller",
    "worklogger.presentation.reporting.dialog",
    "worklogger.presentation.theme.theme_engine",
    "worklogger.presentation.auth",
    "worklogger.presentation.auth.controller",
    "worklogger.presentation.auth.dialogs",
    "worklogger.presentation.settings",
    "worklogger.presentation.settings.controller",
    "worklogger.presentation.settings.dialog",
    "worklogger.presentation.user_management",
    "worklogger.presentation.user_management.dialog",
    "worklogger.presentation.shell.app_window",
    "worklogger.presentation.shell.minimal_view",
    "worklogger.presentation.shell.residency",
    "worklogger.presentation.viewmodels.auth",
    "worklogger.presentation.viewmodels.ai_assist",
    "worklogger.presentation.viewmodels.analytics",
    "worklogger.presentation.viewmodels.auto_record",
    "worklogger.presentation.viewmodels.calendar",
    "worklogger.presentation.viewmodels.data_management",
    "worklogger.presentation.viewmodels.identity",
    "worklogger.presentation.viewmodels.local_models",
    "worklogger.presentation.viewmodels.notes",
    "worklogger.presentation.viewmodels.quick_logs",
    "worklogger.presentation.viewmodels.reports",
    "worklogger.presentation.viewmodels.settings",
    "worklogger.presentation.viewmodels.stats",
    "worklogger.presentation.viewmodels.user_management",
    "worklogger.presentation.viewmodels.worklog_entry",
    "worklogger.presentation.widgets.calendar",
    "worklogger.presentation.widgets.combo_chart",
    "worklogger.presentation.widgets.stats",
    "worklogger.presentation.widgets.switch_button",
    "worklogger.presentation.widgets.worklog_entry",
    "worklogger.presentation",
)


def _safe_stdout(message: str) -> None:
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        print(message)


def smoke_import_check() -> int:
    failures: list[str] = []
    for module_name in SMOKE_IMPORT_MODULES:
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            failures.append(f"{module_name}: {type(exc).__name__}: {exc}")
    if failures:
        _safe_stdout(_("SMOKE IMPORT FAILED"))
        for failure in failures:
            _safe_stdout(failure)
        return 1
    _safe_stdout(_("SMOKE IMPORT OK"))
    return 0


def smoke_runtime_check() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from worklogger.bootstrap import DesktopRuntimeConfig, build_desktop_runtime

    with tempfile.TemporaryDirectory() as directory:
        runtime = build_desktop_runtime(
            DesktopRuntimeConfig(
                database_path=os.path.join(directory, "worklog.db"),
                create_user_if_empty=True,
                password_iterations=1_000,
            ),
            argv=[],
        )
        if not runtime.ok or runtime.value is None:
            _safe_stdout(_("RUNTIME SMOKE FAILED"))
            if runtime.error:
                _safe_stdout(_(runtime.error.message))
            return 1
        refreshed = runtime.value.window.refresh()
        runtime.value.window.close()
        if not refreshed:
            _safe_stdout(_("RUNTIME SMOKE FAILED"))
            if runtime.value.window.last_error:
                _safe_stdout(_(runtime.value.window.last_error.message))
            return 1
    _safe_stdout(_("RUNTIME SMOKE OK"))
    return 0


def run_desktop(args: Sequence[str]) -> int:
    from worklogger.bootstrap import (
        DesktopRuntimeConfig,
        build_authenticated_desktop_runtime,
    )

    exit_code = 0
    while True:
        runtime = build_authenticated_desktop_runtime(
            DesktopRuntimeConfig(),
            argv=list(args),
        )
        if not runtime.ok or runtime.value is None:
            _safe_stdout(_("DESKTOP START FAILED"))
            if runtime.error:
                _safe_stdout(_(runtime.error.message))
            return 1

        logged_out = False

        def request_logout() -> None:
            nonlocal logged_out
            logged_out = True
            runtime.value.remember_session_store.clear_token()
            runtime.value.window.close()
            runtime.value.application.quit()

        if hasattr(runtime.value.window, "logout_requested"):
            runtime.value.window.logout_requested.connect(request_logout)
        runtime.value.window.refresh()
        runtime.value.window.show()
        exit_code = int(runtime.value.application.exec())
        if not logged_out:
            return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    desktop_runner: DesktopRunner = run_desktop,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args:
        _safe_stdout(_("WorkLogger command line"))
        _safe_stdout(_("No arguments start the desktop application."))
        _safe_stdout("--desktop")
        _safe_stdout("--smoke-import")
        _safe_stdout("--smoke-runtime")
        _safe_stdout("--smoke-startup")
        return 0
    if "--smoke-import" in args:
        return smoke_import_check()
    if "--smoke-runtime" in args or "--smoke-startup" in args:
        return smoke_runtime_check()
    if "--desktop" in args:
        return desktop_runner([arg for arg in args if arg != "--desktop"])
    return desktop_runner(args)


if __name__ == "__main__":
    raise SystemExit(main())
