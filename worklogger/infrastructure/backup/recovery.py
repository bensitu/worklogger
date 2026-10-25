"""Private local recovery archives created before personal cloud restores."""

from datetime import datetime, timezone
from uuid import uuid4
from pathlib import Path
import logging
import shutil

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
        retained = sorted((item for item in self.directory.glob("*.wlbackup") if item != path),
                          key=lambda item: item.stat().st_mtime_ns, reverse=True)
        for previous in retained[2:]:
            try:
                previous.unlink()
            except OSError:
                logging.getLogger(__name__).warning("personal_recovery_cleanup_failed")
        return path

    def read(self, path):
        with Path(path).open("rb") as stream:
            content = stream.read(MAX_BACKUP_BYTES + 1)
        if len(content) > MAX_BACKUP_BYTES:
            raise ValueError("cloud_backup_too_large")
        return content


def remove_account_recovery(user_id, database_path):
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id_invalid")
    root = Path(database_path).resolve().parent / "personal-recovery"
    directory = root / str(user_id)
    if root.is_symlink() or directory.is_symlink():
        raise OSError("personal_recovery_path_invalid")
    if directory.exists():
        if directory.resolve().parent != root.resolve():
            raise OSError("personal_recovery_path_invalid")
        shutil.rmtree(directory)
