"""Credential file locations with stable access to existing installations."""

import os
import sys
from pathlib import Path

from worklogger.config.constants import MACHINE_KEY_FILENAME, REMEMBER_SESSION_FILENAME


def credential_directory() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "WorkLogger"
    previous = Path.home() / ".config" / "worklogger"
    if sys.platform == "darwin" and not any((previous / name).exists() for name in
                                           (MACHINE_KEY_FILENAME, REMEMBER_SESSION_FILENAME)):
        return Path.home() / "Library" / "Application Support" / "WorkLogger"
    return previous
