"""Desktop context dependency composition."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from worklogger.app.use_cases.ai import (
    AiChatHandler,
    RewriteTextHandler,
)
from worklogger.app.use_cases.reports import (
    ResetReportTemplateHandler,
    SaveReportTemplateHandler,
)
from worklogger.app.use_cases.settings import GetSettingHandler, ProxyPasswordSettings, SetSettingHandler
from worklogger.app.use_cases.work_logs import (
    GetMonthRecordsHandler,
)
from worklogger.config.feature_flags import FeatureFlags
from worklogger.domain.auth.models import User
from worklogger.domain.auth.repositories import AuthCredentialRepository, UserProfileRepository
from worklogger.infrastructure.ai.account import AccountAIGateway
from worklogger.infrastructure.ai.runtime import LocalInferenceRuntime
from worklogger.infrastructure.calendar import (
    PythonHolidaysProvider,
)
from worklogger.infrastructure.calendar.holidays_provider import validate_holiday_region
from worklogger.infrastructure.database import (
    SQLiteConnectionFactory,
)
from worklogger.infrastructure.export import (
    MarkdownExporter,
)
from worklogger.infrastructure.local_model import JsonLocalModelStore, bundled_model_catalog_path
from worklogger.infrastructure.local_model.store import HttpRangeDownloader
from worklogger.infrastructure.network import AccountHTTPTransport
from worklogger.infrastructure.runtime_config import load_runtime_configuration
from worklogger.infrastructure.repositories import (
    SQLiteCalendarEventRepository,
    SQLiteDailyNoteRepository,
    SQLiteIdentityRepository,
    SQLiteQuickLogRepository,
    SQLiteReportRepository,
    SQLiteReportTemplateRepository,
    SQLiteSettingsRepository,
    SQLiteWorkLogRepository,
)
from worklogger.infrastructure.repositories.background_sqlite import SQLiteBackgroundRepository
from worklogger.infrastructure.repositories.project_sqlite import SQLiteProjectRepository
from worklogger.infrastructure.repositories.work_type_sqlite import (
    SQLiteWorkTypeRepository,
)
from worklogger.infrastructure.security.account_credentials import account_credential_namespaces
from worklogger.infrastructure.security.key_store import (
    EncryptedSettingsKeyStore,
    FernetSecretBox,
    SystemCredentialStore,
)
from worklogger.infrastructure.templates import (
    BuiltInTemplateProvider,
    UserTemplateProvider,
)


class RuntimeAuthRepository(AuthCredentialRepository, UserProfileRepository, Protocol):
    def get_by_username(self, username: str) -> User | None: ...


@dataclass(frozen=True)
class RuntimeRepositories:
    work_logs: SQLiteWorkLogRepository
    calendar_events: SQLiteCalendarEventRepository
    daily_notes: SQLiteDailyNoteRepository
    identities: SQLiteIdentityRepository
    quick_logs: SQLiteQuickLogRepository
    reports: SQLiteReportRepository
    report_templates: SQLiteReportTemplateRepository
    settings: SQLiteSettingsRepository
    work_types: SQLiteWorkTypeRepository
    projects: SQLiteProjectRepository
    background_images: SQLiteBackgroundRepository


@dataclass(frozen=True)
class RuntimeHandlers:
    templates: UserTemplateProvider
    markdown_exporter: MarkdownExporter
    rewrite_handler: RewriteTextHandler
    ai_chat_handler: AiChatHandler
    save_template_handler: SaveReportTemplateHandler
    reset_template_handler: ResetReportTemplateHandler
    settings_get_handler: GetSettingHandler
    settings_set_handler: SetSettingHandler
    month_records_handler: GetMonthRecordsHandler
    holiday_provider: PythonHolidaysProvider
    holiday_country: str
    local_inference: LocalInferenceRuntime | None = None
    network_transport: AccountHTTPTransport | None = None
    ai_gateway: AccountAIGateway | None = None
    external_keys: object | None = None
    proxy_password: object | None = None
    user_profiles: UserProfileRepository | None = None


def build_runtime_repositories(
    connection_factory: SQLiteConnectionFactory,
) -> RuntimeRepositories:
    return RuntimeRepositories(
        work_logs=SQLiteWorkLogRepository(connection_factory),
        calendar_events=SQLiteCalendarEventRepository(connection_factory),
        daily_notes=SQLiteDailyNoteRepository(connection_factory),
        identities=SQLiteIdentityRepository(connection_factory),
        quick_logs=SQLiteQuickLogRepository(connection_factory),
        reports=SQLiteReportRepository(connection_factory),
        report_templates=SQLiteReportTemplateRepository(connection_factory),
        settings=SQLiteSettingsRepository(connection_factory),
        work_types=SQLiteWorkTypeRepository(connection_factory),
        projects=SQLiteProjectRepository(connection_factory),
        background_images=SQLiteBackgroundRepository(connection_factory),
    )


def build_runtime_handlers(
    repositories: RuntimeRepositories, *, holiday_country: str, user_id=None, database_path=None,
    user_profiles: UserProfileRepository | None = None,
) -> RuntimeHandlers:
    inference = None
    features = FeatureFlags.from_env()
    transport = gateway = external_keys = proxy_password = None
    if user_id is not None and database_path is not None:
        external_service, namespace = account_credential_namespaces(user_id, database_path)
        external_keys = EncryptedSettingsKeyStore(repositories.settings, user_id=user_id,
            service_name=external_service)
        proxy_password = ProxyPasswordSettings(repositories.settings, SystemCredentialStore(namespace=namespace),
                                               user_id=user_id, secret_box=FernetSecretBox())
        transport = AccountHTTPTransport(settings=repositories.settings, user_id=user_id, proxy_password=proxy_password)
        opener = transport.opener(public_only=True)
        store = JsonLocalModelStore(Path(database_path).parent / "models", bundled_catalog_path=bundled_model_catalog_path(),
            catalog_opener=opener, downloader=HttpRangeDownloader(opener=opener),
            remote_catalog_url=os.environ.get("WORKLOGGER_MODEL_CATALOG_URL", "").strip() or None)
        inference = LocalInferenceRuntime(store=store, settings=repositories.settings, user_id=user_id,
            enabled=features.enable_ai)
        gateway = AccountAIGateway(local=inference, settings=repositories.settings, user_id=user_id,
            key_store=external_keys, transport=transport, enabled=features.enable_ai,
            model_profiles=load_runtime_configuration().external_model_profiles)
    return RuntimeHandlers(
        templates=UserTemplateProvider(
            repositories.report_templates,
            BuiltInTemplateProvider(),
        ),
        markdown_exporter=MarkdownExporter(),
        rewrite_handler=RewriteTextHandler(gateway, timeout_seconds=180, profiles=user_profiles),
        ai_chat_handler=AiChatHandler(gateway, timeout_seconds=180, profiles=user_profiles),
        save_template_handler=SaveReportTemplateHandler(repositories.report_templates),
        reset_template_handler=ResetReportTemplateHandler(
            repositories.report_templates
        ),
        settings_get_handler=GetSettingHandler(repositories.settings),
        settings_set_handler=SetSettingHandler(repositories.settings, holiday_region_validator=validate_holiday_region),
        month_records_handler=GetMonthRecordsHandler(repositories.work_logs),
        holiday_provider=PythonHolidaysProvider(),
        holiday_country=holiday_country,
        local_inference=inference,
        network_transport=transport,
        ai_gateway=gateway,
        external_keys=external_keys,
        proxy_password=proxy_password,
        user_profiles=user_profiles,
    )
