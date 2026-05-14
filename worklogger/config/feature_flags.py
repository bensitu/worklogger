"""Feature flag definitions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class FeatureFlag(str, Enum):
    AI = "ai"
    LOCAL_MODELS = "local_models"
    GOOGLE_IDENTITY = "google_identity"
    MICROSOFT_IDENTITY = "microsoft_identity"
    ANALYTICS_PDF_NARRATIVE = "analytics_pdf_narrative"
    UPDATE_CHECK = "update_check"


def _env_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FeatureFlags:
    enable_ai: bool = True
    enable_local_models: bool = True
    enable_google_identity: bool = False
    enable_microsoft_identity: bool = False
    enable_analytics_pdf_narrative: bool = True
    enable_update_check: bool = True

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "FeatureFlags":
        source = environ if environ is not None else os.environ
        return cls(
            enable_ai=_env_bool(source, "WORKLOGGER_FEATURE_AI", cls.enable_ai),
            enable_local_models=_env_bool(
                source,
                "WORKLOGGER_FEATURE_LOCAL_MODELS",
                cls.enable_local_models,
            ),
            enable_google_identity=_env_bool(
                source,
                "WORKLOGGER_FEATURE_GOOGLE_IDENTITY",
                cls.enable_google_identity,
            ),
            enable_microsoft_identity=_env_bool(
                source,
                "WORKLOGGER_FEATURE_MICROSOFT_IDENTITY",
                cls.enable_microsoft_identity,
            ),
            enable_analytics_pdf_narrative=_env_bool(
                source,
                "WORKLOGGER_FEATURE_ANALYTICS_PDF_NARRATIVE",
                cls.enable_analytics_pdf_narrative,
            ),
            enable_update_check=_env_bool(
                source,
                "WORKLOGGER_FEATURE_UPDATE_CHECK",
                cls.enable_update_check,
            ),
        )

    def is_enabled(self, flag: FeatureFlag) -> bool:
        return {
            FeatureFlag.AI: self.enable_ai,
            FeatureFlag.LOCAL_MODELS: self.enable_local_models,
            FeatureFlag.GOOGLE_IDENTITY: self.enable_google_identity,
            FeatureFlag.MICROSOFT_IDENTITY: self.enable_microsoft_identity,
            FeatureFlag.ANALYTICS_PDF_NARRATIVE: self.enable_analytics_pdf_narrative,
            FeatureFlag.UPDATE_CHECK: self.enable_update_check,
        }[flag]
