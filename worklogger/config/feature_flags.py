"""Feature flag definitions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class FeatureFlag(str, Enum):
    AI = "ai"
    LOCAL_MODELS = "local_models"
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
            FeatureFlag.UPDATE_CHECK: self.enable_update_check,
        }[flag]
