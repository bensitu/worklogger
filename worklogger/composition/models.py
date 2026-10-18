"""Desktop models dependency composition."""

from __future__ import annotations

from pathlib import Path

from worklogger.app.job_runner import JobRunner
from worklogger.app.use_cases.local_models import (
    DeleteLocalModelHandler,
    DownloadLocalModelHandler,
    ImportLocalModelHandler,
    ListLocalModelsHandler,
    RefreshLocalModelCatalogHandler,
    SelectLocalModelHandler,
    VerifyLocalModelHandler,
)
from worklogger.composition.context import RuntimeRepositories, build_local_model_store
from worklogger.domain.auth.models import User
from worklogger.presentation.local_models import LocalModelsWorkflowController
from worklogger.presentation.viewmodels import (
    LocalModelManagerViewModel,
)


def build_local_models_workflow(
    *,
    user: User,
    database_path: Path,
    repositories: RuntimeRepositories,
    job_runner: JobRunner | None,
    store=None,
    before_delete=None,
) -> LocalModelsWorkflowController:
    local_model_store = store or build_local_model_store(database_path)
    return LocalModelsWorkflowController(
        LocalModelManagerViewModel(
            user_id=user.id,
            list_handler=ListLocalModelsHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            refresh_handler=RefreshLocalModelCatalogHandler(local_model_store),
            import_handler=ImportLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            download_handler=DownloadLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            verify_handler=VerifyLocalModelHandler(local_model_store),
            select_handler=SelectLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
            ),
            delete_handler=DeleteLocalModelHandler(
                store=local_model_store,
                settings=repositories.settings,
                usage_reader=repositories.settings,
                before_delete=before_delete,
            ),
        ),
        job_runner=job_runner,
    )
