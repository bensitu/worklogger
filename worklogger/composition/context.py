"""Desktop context dependency composition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from worklogger.app.use_cases.ai import (
    AiChatHandler,
    RewriteTextHandler,
)
from worklogger.app.use_cases.reports import (
    ResetReportTemplateHandler,
    SaveReportTemplateHandler,
)
from worklogger.app.use_cases.settings import GetSettingHandler, SetSettingHandler
from worklogger.app.use_cases.work_logs import (
    GetMonthRecordsHandler,
)
from worklogger.domain.auth.models import User
from worklogger.domain.auth.repositories import AuthCredentialRepository
from worklogger.domain.auth.repositories import UserProfileRepository
from worklogger.infrastructure.calendar import (
    PythonHolidaysProvider,
)
from worklogger.infrastructure.database import (
    SQLiteConnectionFactory,
)
from worklogger.infrastructure.export import (
    MarkdownExporter,
)
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
from worklogger.infrastructure.repositories.work_type_sqlite import (
    SQLiteWorkTypeRepository,
)
from worklogger.infrastructure.templates import (
    BuiltInTemplateProvider,
    UserTemplateProvider,
)
from worklogger.infrastructure.ai.runtime import LocalInferenceRuntime
from worklogger.infrastructure.local_model import JsonLocalModelStore, bundled_model_catalog_path
from worklogger.config.feature_flags import FeatureFlags
from pathlib import Path
import os
import hashlib
from worklogger.app.use_cases.settings import ProxyPasswordSettings
from worklogger.infrastructure.network import AccountHTTPTransport
from worklogger.infrastructure.ai.account import AccountAIGateway
from worklogger.infrastructure.repositories.project_sqlite import SQLiteProjectRepository
from worklogger.infrastructure.security.key_store import EncryptedSettingsKeyStore, SystemCredentialStore, HmacSecretBox
from worklogger.infrastructure.local_model.store import HttpRangeDownloader


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


def _runtime_repositories(
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
    )


def _runtime_handlers(
    repositories: RuntimeRepositories, *, holiday_country: str, user_id=None, database_path=None,
    user_profiles: UserProfileRepository | None = None,
) -> RuntimeHandlers:
    inference = None
    transport = gateway = external_keys = proxy_password = None
    if user_id is not None and database_path is not None:
        namespace = str(Path(database_path).resolve())
        external_keys = EncryptedSettingsKeyStore(repositories.settings, user_id=user_id,
            service_name="worklogger.external." + hashlib.sha256((namespace + ":" + str(user_id)).encode()).hexdigest())
        proxy_password = ProxyPasswordSettings(repositories.settings, SystemCredentialStore(namespace=namespace),
                                               user_id=user_id, secret_box=HmacSecretBox())
        transport = AccountHTTPTransport(settings=repositories.settings, user_id=user_id, proxy_password=proxy_password)
        opener = transport.opener(public_only=True)
        store = JsonLocalModelStore(Path(database_path).parent / "models", bundled_catalog_path=bundled_model_catalog_path(),
            catalog_opener=opener, downloader=HttpRangeDownloader(opener=opener),
            remote_catalog_url=os.environ.get("WORKLOGGER_MODEL_CATALOG_URL", "").strip() or None)
        inference = LocalInferenceRuntime(store=store, settings=repositories.settings, user_id=user_id,
            enabled=FeatureFlags.from_env().enable_ai)
        gateway = AccountAIGateway(local=inference, settings=repositories.settings, user_id=user_id,
            key_store=external_keys, transport=transport, enabled=FeatureFlags.from_env().enable_ai)
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
        settings_set_handler=SetSettingHandler(repositories.settings),
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
