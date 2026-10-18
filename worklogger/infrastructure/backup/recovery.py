"""Private local recovery archives created before personal cloud restores."""

from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path

from worklogger.domain.cloud_backup import MAX_BACKUP_BYTES
from worklogger.infrastructure.files import atomic_destination


class PersonalRecoveryStore:
    def __init__(self, directory):
        self.directory = directory

    def __call__(self, content):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex + ".wlbackup"
        path = self.directory / name
        with atomic_destination(path) as temporary:
            temporary.write_bytes(content)
        return path

    def read(self, path):
        with Path(path).open("rb") as stream:
            content = stream.read(MAX_BACKUP_BYTES + 1)
        if len(content) > MAX_BACKUP_BYTES:
            raise ValueError("cloud_backup_too_large")
        return content
