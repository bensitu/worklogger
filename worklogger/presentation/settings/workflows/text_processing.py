"""AI configuration, model status, and cancellable connection checks."""

from collections.abc import Callable
from weakref import WeakKeyDictionary

from PySide6.QtCore import QObject
from shiboken6 import isValid

from worklogger.app.ports import AIRequest
from worklogger.domain.shared.errors import CancellationError, InfrastructureError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.i18n import _
from worklogger.presentation.job_runner import owned_callback, shared_job_runner
from worklogger.presentation.processing import TextProcessingTask
from worklogger.presentation.settings.page import SettingsPage
from worklogger.presentation.settings.workflows.common import _error_message


class TextProcessingSettingsWorkflow:
    def __init__(self, *, settings_view_model, local_models_view_model, capabilities,
                 job_runner, local_inference, ai_gateway, connection_test_timeout_seconds):
        self._settings = settings_view_model
        self._models = local_models_view_model
        self._capabilities = capabilities
        self._job_runner = job_runner
        self._runtime = local_inference
        self._gateway = ai_gateway
        self._connection_test_timeout_seconds = connection_test_timeout_seconds
        self._model_revisions = WeakKeyDictionary()
        self._connection_tests = WeakKeyDictionary()

    def _runner(self):
        return self._job_runner or shared_job_runner()

    def initialize(self, owner: QObject, callback: Callable[[], None]) -> None:
        if not self._capabilities.ai_enabled:
            callback()
            return

        def load(token):
            settings = self._settings.load()
            inventory = self._models.load(cancellation=token) if self._models is not None else None
            return settings, inventory

        def complete(result):
            if result.ok:
                settings, inventory = result.value
                if settings.ok and settings.value is not None and self._gateway is not None:
                    self._gateway.update_configuration(settings.value)
                if inventory is not None and inventory.ok and self._runtime is not None:
                    self._runtime.update_inventory(inventory.value.inventory)
            callback()

        try:
            self._runner().submit("initialize_text_processing", load,
                                  on_complete=owned_callback(owner, complete))
        except Exception:
            callback()

    def bind(self, surface: SettingsPage) -> None:
        if self._runtime is not None or self._gateway is not None:
            surface.settings_changed.connect(lambda _state: self.sync(surface))
        if self._gateway is not None:
            surface.test_external_model_requested.connect(lambda: self.test_connection(surface))
        self.refresh_models(surface)

    def refresh_models(self, surface: SettingsPage, *, retry: bool = True) -> None:
        if not self._capabilities.ai_enabled or self._models is None:
            return
        revision = self._model_revisions.get(surface, 0) + 1
        self._model_revisions[surface] = revision

        def complete(result):
            if not isValid(surface) or self._model_revisions.get(surface) != revision:
                return
            if not result.ok or result.value is None:
                surface.set_local_model_error(result.error)
                return
            inventory = result.value.inventory
            if self._runtime is not None and self._runtime.update_inventory(inventory) is False:
                if retry:
                    self.refresh_models(surface, retry=False)
                else:
                    surface.set_local_model_error(InfrastructureError(
                        "local_model_list_failed", "local_model_list_failed"))
                return
            active = next((item for item in inventory.items
                           if item.entry.id == inventory.active_model_id), None)
            surface.set_local_model_status(
                ready=active is not None and active.verified,
                name=active.entry.display_name if active is not None else "",
            )
            surface.set_local_model_context_limit(active.entry.context_length if active is not None else None)
            self.sync(surface)

        try:
            self._runner().submit("local_model_status", lambda token: self._models.load(cancellation=token),
                                  on_complete=complete)
        except Exception:
            complete(Result.failure(InfrastructureError("local_model_list_failed", "local_model_list_failed")))

    def sync(self, surface: SettingsPage) -> None:
        if self._gateway is not None and surface.state is not None:
            self._gateway.update_configuration(surface.state)
        if self._runtime is not None:
            surface.set_local_runtime_status(ready=self._runtime.available, reason=self._runtime.reason)
        if self._runtime is not None or self._gateway is not None:
            surface.ai_availability_changed.emit()

    def test_connection(self, surface: SettingsPage) -> None:
        if not self._capabilities.ai_enabled or surface.is_busy or self._gateway is None:
            return
        surface.set_busy("external_model_test", True)
        surface.set_external_test_status("")
        task = self._connection_tests.get(surface)
        if task is None:
            task = TextProcessingTask(surface, job_runner=self._job_runner)
            self._connection_tests[surface] = task
            surface.destroyed.connect(task.cancel)
            surface.destroyed.connect(lambda: self._connection_tests.pop(surface, None))
            surface.bind_external_test_progress(task)

        def complete(result):
            if not isValid(surface):
                return
            surface.set_busy("external_model_test", False)
            surface.set_external_test_status(_("Connection succeeded.") if result.ok else
                _("Operation cancelled.") if isinstance(result.error, CancellationError) else _error_message(result.error))

        task.run("ai_test_external_model", lambda token: self._gateway.generate(AIRequest(
            messages=({"role": "user", "content": "Reply with OK."},), model="default",
            timeout_seconds=self._connection_test_timeout_seconds, cancellation_token=token)),
            on_complete=complete)
