"""Desktop models dependency composition."""

from __future__ import annotations

import os
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
from worklogger.composition.context import RuntimeRepositories
from worklogger.domain.auth.models import User
from worklogger.infrastructure.local_model import (
    JsonLocalModelStore,
    bundled_model_catalog_path,
)
from worklogger.presentation.local_models import LocalModelsWorkflowController
from worklogger.presentation.viewmodels import (
    LocalModelManagerViewModel,
)


def _build_local_models_workflow(
    *,
    user: User,
    database_path: Path,
    repositories: RuntimeRepositories,
    job_runner: JobRunner | None,
) -> LocalModelsWorkflowController:
    local_model_store = JsonLocalModelStore(
        database_path.parent / "models",
        bundled_catalog_path=bundled_model_catalog_path(),
        remote_catalog_url=os.environ.get("WORKLOGGER_MODEL_CATALOG_URL", "").strip()
        or None,
    )
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
            ),
        ),
        job_runner=job_runner,
    )
