"""Entry point for the WorkLogger desktop application."""

from __future__ import annotations

import importlib
import logging
import os
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

if __package__ in {None, ""}:
    workspace_root = str(Path(__file__).resolve().parents[1])
    if workspace_root not in sys.path:
        sys.path.insert(0, workspace_root)

from worklogger.domain.shared.errors import CancellationError
from worklogger.infrastructure.i18n import _, set_language
from worklogger.presentation.errors import display_error_message

DesktopRunner = Callable[[Sequence[str]], int]
LOGGER = logging.getLogger(__name__)

SMOKE_IMPORT_MODULES = (
    "worklogger.bootstrap",
    "worklogger.presentation.auth",
    "worklogger.presentation.settings",
    "worklogger.presentation.shell",
    "worklogger.infrastructure",
)


def _import_modules():
    import pkgutil
    import worklogger

    modules = set(SMOKE_IMPORT_MODULES)
    modules.update(info.name for info in pkgutil.walk_packages(worklogger.__path__, "worklogger.")
                   if not info.name.startswith("worklogger._vendor"))
    return sorted(modules)


def _safe_stdout(message: str) -> None:
    stream = getattr(sys, "stdout", None)
    if stream is not None:
        try:
            print(message, file=stream)
        except UnicodeEncodeError:
            encoding = getattr(stream, "encoding", None) or "ascii"
            print(message.encode(encoding, errors="replace").decode(encoding), file=stream)


class DesktopAlreadyRunningError(RuntimeError):
    """Another desktop process owns the database lock."""


def _acquire_instance_lock(database_path: Path | None = None):
    from PySide6.QtCore import QLockFile
    from worklogger.infrastructure.database.paths import default_database_path

    path = (database_path or default_database_path()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = QLockFile(str(path) + ".lock")
    if not lock.tryLock(0):
        if lock.error() == QLockFile.LockError.LockFailedError:
            raise DesktopAlreadyRunningError("desktop_already_running")
        raise OSError("desktop_lock_unavailable")
    return lock


def _startup_message(message: str, *, error: bool = True) -> None:
    _safe_stdout(message)
    if os.environ.get("QT_QPA_PLATFORM") in {"offscreen", "minimal"}:
        return
    from PySide6.QtWidgets import QMessageBox
    from worklogger.bootstrap import _application
    from worklogger.__about__ import APP_NAME

    _application_instance = _application([])
    show = QMessageBox.critical if error else QMessageBox.information
    show(None, APP_NAME, message)


def smoke_import_check() -> int:
    failures: list[str] = []
    for module_name in _import_modules():
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
                _safe_stdout(display_error_message(runtime.error))
            return 1
        refreshed = runtime.value.window.refresh()
        runtime.value.window.close()
        if not refreshed:
            _safe_stdout(_("RUNTIME SMOKE FAILED"))
            if runtime.value.window.last_error:
                _safe_stdout(display_error_message(runtime.value.window.last_error))
            return 1
    _safe_stdout(_("RUNTIME SMOKE OK"))
    return 0


def run_desktop(args: Sequence[str]) -> int:
    try:
        lock = _acquire_instance_lock()
    except DesktopAlreadyRunningError:
        _startup_message(_("WorkLogger is already running."), error=False)
        return 0
    except OSError:
        _startup_message(_("Unable to start WorkLogger. Check the application log for details."))
        return 1
    try:
        return _run_desktop(args)
    finally:
        lock.unlock()


def _run_desktop(args: Sequence[str]) -> int:
    from worklogger.bootstrap import (
        DesktopRuntimeConfig,
        build_authenticated_desktop_runtime,
    )

    exit_code = 0
    skip_remembered_session = False
    while True:
        runtime = build_authenticated_desktop_runtime(
            DesktopRuntimeConfig(skip_remembered_session=skip_remembered_session),
            argv=list(args),
        )
        if not runtime.ok or runtime.value is None:
            if isinstance(runtime.error, CancellationError):
                return 0
            if runtime.error is not None and runtime.error.code == "restore_pending":
                if os.environ.get("QT_QPA_PLATFORM") in {"offscreen", "minimal"}:
                    _startup_message(display_error_message(runtime.error))
                    return 1
                from worklogger.bootstrap import _application
                from worklogger.infrastructure.language_preferences import LanguagePreferences, initialize_language
                from worklogger.infrastructure.database.paths import default_database_path
                from worklogger.infrastructure.database.restore_recovery import inspect_pending_restore, recover_pending_restore
                from worklogger.presentation.widgets.restore_recovery import choose_restore_recovery

                try:
                    _recovery_application = _application(list(args))
                    initialize_language(LanguagePreferences())
                    path = default_database_path()
                    choice = choose_restore_recovery(inspect_pending_restore(path))
                    if choice is None:
                        return 0
                    recover_pending_restore(path, choice)
                except Exception as error:
                    LOGGER.error("restore_recovery_failed: %s", type(error).__name__)
                    _startup_message(display_error_message(runtime.error))
                    return 1
                continue
            _safe_stdout(_("DESKTOP START FAILED"))
            _startup_message(display_error_message(runtime.error))
            return 1

        logged_out = False
        current = runtime.value

        def request_logout(current=current) -> None:
            nonlocal logged_out, skip_remembered_session
            revoke = getattr(current, "revoke_remembered_session", None)
            if revoke is not None:
                revoked = revoke()
                if not revoked.ok:
                    _startup_message(display_error_message(revoked.error))
                    return
            cleared = current.remember_session_store.clear_token()
            if cleared is not None and not cleared.ok:
                if revoke is None:
                    _startup_message(display_error_message(cleared.error))
                    return
                _startup_message(_("The account's remembered session was revoked, but its device file could not be removed. Sign in manually and check storage permissions."), error=False)
            logged_out = True
            skip_remembered_session = True
            current.window.close()
            current.application.quit()

        if hasattr(current.window, "logout_requested"):
            current.window.logout_requested.connect(request_logout)
        current.window.refresh()
        current.window.show()
        exit_code = int(current.application.exec())
        runner = getattr(current, "job_runner", None)
        if runner is not None:
            runner.shutdown(wait=True)
        inference = getattr(current, "local_inference", None)
        if inference is not None:
            inference.close()
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QWidget
        from shiboken6 import isValid

        if isinstance(current.window, QWidget) and isValid(current.window):
            current.window.deleteLater()
            QCoreApplication.sendPostedEvents(current.window, QEvent.Type.DeferredDelete)
        if not logged_out:
            return exit_code


def main(
    argv: Sequence[str] | None = None,
    *,
    desktop_runner: DesktopRunner = run_desktop,
) -> int:
    set_language(os.environ.get("WORKLOGGER_LANG"))
    args = list(sys.argv[1:] if argv is None else argv)
    if "--smoke-local-model-runtime" in args:
        from worklogger.diagnostics import check_local_model_runtime
        try:
            check_local_model_runtime()
        except Exception as error:
            _safe_stdout(_("RUNTIME SMOKE FAILED") + " " + type(error).__name__)
            return 1
        _safe_stdout(_("RUNTIME SMOKE OK"))
        return 0
    if "--smoke-workflows" in args:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from worklogger.diagnostics import check_workflows
        try:
            check_workflows()
        except Exception as error:
            _safe_stdout(_("Workflow verification failed.") + " " + type(error).__name__)
            return 1
        _safe_stdout(_("Workflow verification passed."))
        return 0
    if "--help" in args or "-h" in args:
        _safe_stdout(_("WorkLogger command line"))
        _safe_stdout(_("No arguments start the desktop application."))
        _safe_stdout("--desktop")
        _safe_stdout("--smoke-import")
        _safe_stdout("--smoke-runtime")
        _safe_stdout("--smoke-startup")
        _safe_stdout("--smoke-local-model-runtime")
        _safe_stdout("--smoke-workflows")
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
