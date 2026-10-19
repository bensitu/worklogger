"""Bounded deployment configuration, separate from account preferences."""

import json
import logging
import sys
from dataclasses import dataclass, fields, replace
from pathlib import Path

from worklogger.config.constants import DEFAULT_CLOUD_BACKUP_STARTUP_DELAY_SECONDS
from worklogger.infrastructure.ai.generation_options import ExternalModelProfile, external_model_profiles

LOGGER = logging.getLogger(__name__)
CONFIG_FILENAME = "worklogger.config.json"
MAX_CONFIG_BYTES = 64 * 1024


@dataclass(frozen=True)
class DeploymentFeatures:
    background_images: bool = False
    minimal_view: bool = False
    ai: bool = True
    cloud_backup: bool = True
    self_registration: bool = True
    oidc: bool = True


@dataclass(frozen=True)
class CloudBackupRuntimeConfiguration:
    startup_delay_seconds: int = DEFAULT_CLOUD_BACKUP_STARTUP_DELAY_SECONDS
    check_interval_seconds: int = 60
    retry_initial_seconds: int = 300
    retry_max_seconds: int = 3600


@dataclass(frozen=True)
class AiRuntimeConfiguration:
    rewrite_timeout_seconds: int = 180
    chat_timeout_seconds: int = 180
    connection_test_timeout_seconds: int = 30


@dataclass(frozen=True)
class LocalModelsRuntimeConfiguration:
    download_timeout_seconds: int = 30
    catalog_timeout_seconds: int = 15


@dataclass(frozen=True)
class PaginationRuntimeConfiguration:
    notes_page_size: int = 50
    records_page_size: int = 100
    reports_page_size: int = 50


@dataclass(frozen=True)
class RuntimeConfiguration:
    features: DeploymentFeatures = DeploymentFeatures()
    external_model_profiles: tuple[ExternalModelProfile, ...] = ()
    cloud_backup: CloudBackupRuntimeConfiguration = CloudBackupRuntimeConfiguration()
    ai: AiRuntimeConfiguration = AiRuntimeConfiguration()
    local_models: LocalModelsRuntimeConfiguration = LocalModelsRuntimeConfiguration()
    pagination: PaginationRuntimeConfiguration = PaginationRuntimeConfiguration()
    valid: bool = True


def configuration_path(*, frozen=None, executable=None, bundle_root=None, source_root=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        return Path(source_root or Path(__file__).resolve().parents[2]) / CONFIG_FILENAME
    adjacent = Path(executable or sys.executable).resolve().parent / CONFIG_FILENAME
    if adjacent.exists():
        return adjacent
    return Path(bundle_root or getattr(sys, "_MEIPASS", adjacent.parent)) / CONFIG_FILENAME


def _integer_configuration(value, key, configuration_type, bounds):
    defaults = configuration_type()
    options = value.get(key, {})
    if not isinstance(options, dict):
        LOGGER.warning("%s_runtime_configuration_invalid", key)
        return defaults
    parsed, invalid = {}, False
    for name, (minimum, maximum) in bounds.items():
        default = getattr(defaults, name)
        candidate = options.get(name, default)
        if type(candidate) is int and minimum <= candidate <= maximum:
            parsed[name] = candidate
        else:
            parsed[name], invalid = default, True
    if invalid:
        LOGGER.warning("%s_runtime_configuration_invalid", key)
    return configuration_type(**parsed)


def load_runtime_configuration(path=None):
    path = Path(path) if path is not None else configuration_path()
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_CONFIG_BYTES + 1)
        if len(data) > MAX_CONFIG_BYTES:
            raise ValueError("runtime_configuration_too_large")
        value = json.loads(data.decode("utf-8-sig"))
        if not isinstance(value, dict) or not isinstance(value.get("features", {}), dict):
            raise TypeError("runtime_configuration_invalid")
        flags = {}
        for field in fields(DeploymentFeatures):
            enabled = value.get("features", {}).get(field.name, field.default)
            if type(enabled) is not bool:
                raise TypeError("runtime_configuration_invalid")
            flags[field.name] = enabled
        features = DeploymentFeatures(**flags)
        try:
            profiles = external_model_profiles(value.get("external_model_profiles", []))
        except (ValueError, TypeError):
            LOGGER.warning("ai_model_profiles_invalid")
            profiles = ()
        backup = _integer_configuration(value, "cloud_backup", CloudBackupRuntimeConfiguration, {
            "startup_delay_seconds": (0, 86400), "check_interval_seconds": (5, 3600),
            "retry_initial_seconds": (5, 86400), "retry_max_seconds": (5, 86400),
        })
        if backup.retry_max_seconds < backup.retry_initial_seconds:
            LOGGER.warning("cloud_backup_runtime_configuration_invalid")
            defaults = CloudBackupRuntimeConfiguration()
            backup = replace(backup, retry_initial_seconds=defaults.retry_initial_seconds,
                             retry_max_seconds=defaults.retry_max_seconds)
        ai = _integer_configuration(value, "ai", AiRuntimeConfiguration, {
            "rewrite_timeout_seconds": (1, 3600), "chat_timeout_seconds": (1, 3600),
            "connection_test_timeout_seconds": (1, 300),
        })
        local_models = _integer_configuration(value, "local_models", LocalModelsRuntimeConfiguration, {
            "download_timeout_seconds": (1, 600), "catalog_timeout_seconds": (1, 300),
        })
        pagination = _integer_configuration(value, "pagination", PaginationRuntimeConfiguration, {
            "notes_page_size": (1, 100), "records_page_size": (1, 250), "reports_page_size": (1, 250),
        })
        return RuntimeConfiguration(features=features, external_model_profiles=profiles,
            cloud_backup=backup, ai=ai, local_models=local_models, pagination=pagination)
    except FileNotFoundError:
        return RuntimeConfiguration()
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        LOGGER.warning("runtime_configuration_invalid")
        return RuntimeConfiguration(features=DeploymentFeatures(
            ai=False, cloud_backup=False, self_registration=False, oidc=False), valid=False)
