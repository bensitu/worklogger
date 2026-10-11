"""Bounded deployment configuration, separate from account preferences."""

import json
import logging
import sys
from dataclasses import dataclass, fields
from pathlib import Path

LOGGER = logging.getLogger(__name__)
CONFIG_FILENAME = "worklogger.config.json"
MAX_CONFIG_BYTES = 64 * 1024


@dataclass(frozen=True)
class DeploymentFeatures:
    background_images: bool = False
    minimal_view: bool = False


@dataclass(frozen=True)
class RuntimeConfiguration:
    features: DeploymentFeatures = DeploymentFeatures()


def configuration_path(*, frozen=None, executable=None, bundle_root=None, source_root=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        return Path(source_root or Path(__file__).resolve().parents[2]) / CONFIG_FILENAME
    adjacent = Path(executable or sys.executable).resolve().parent / CONFIG_FILENAME
    if adjacent.exists():
        return adjacent
    return Path(bundle_root or getattr(sys, "_MEIPASS", adjacent.parent)) / CONFIG_FILENAME


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
            enabled = value.get("features", {}).get(field.name, False)
            if type(enabled) is not bool:
                raise TypeError("runtime_configuration_invalid")
            flags[field.name] = enabled
        return RuntimeConfiguration(DeploymentFeatures(**flags))
    except FileNotFoundError:
        return RuntimeConfiguration()
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        LOGGER.warning("runtime_configuration_invalid")
        return RuntimeConfiguration()
