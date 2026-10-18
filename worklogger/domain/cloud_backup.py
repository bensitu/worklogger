"""Personal backup configuration, schedules, and transfer metadata."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import calendar
import hashlib
import json
import re
from urllib.parse import urlsplit


MAX_BACKUP_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_BYTES = 128 * 1024 * 1024
CONFIG_KEY = "cloud_backup.configuration"
STATE_KEY = "cloud_backup.state"


@dataclass(frozen=True)
class BackupConfiguration:
    provider: str = "webdav"
    endpoint: str = ""
    prefix: str = "worklogger/personal"
    bucket: str = ""
    region: str = "us-east-1"
    encrypted: bool = True
    keep_count: int = 20
    keep_days: int = 90
    schedule: str = "off"
    interval_hours: int = 24
    time: str = "20:00"
    weekday: int = 6
    month_day: int = 1

    def validate(self):
        address = urlsplit(self.endpoint)
        if (self.provider not in {"webdav", "s3"} or address.scheme != "https" or not address.hostname
                or address.username is not None or address.password is not None or address.query or address.fragment
                or any(ord(char) < 32 for char in self.endpoint)):
            raise ValueError("cloud_configuration_invalid")
        if (not self.prefix or len(self.prefix) > 512 or any(part in {"", ".", ".."} for part in self.prefix.split("/"))
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", self.prefix)):
            raise ValueError("cloud_configuration_invalid")
        if self.provider == "s3" and (not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", self.bucket)
                                      or not re.fullmatch(r"[a-z0-9-]{1,64}", self.region)):
            raise ValueError("cloud_configuration_invalid")
        numbers = ((self.keep_count, 1, 200), (self.keep_days, 1, 3650),
                   (self.interval_hours, 1, 8760), (self.weekday, 0, 6), (self.month_day, 1, 31))
        if (type(self.encrypted) is not bool or any(type(value) is not int or not low <= value <= high for value, low, high in numbers)
                or self.schedule not in {"off", "interval", "daily", "weekly", "monthly"}
                or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", self.time)):
            raise ValueError("cloud_configuration_invalid")
        return self

    @property
    def destination(self):
        return hashlib.sha256(json.dumps((self.provider, self.endpoint.rstrip("/"), self.bucket, self.prefix)).encode()).hexdigest()


@dataclass(frozen=True)
class BackupCredentials:
    username: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    session_token: str = field(default="", repr=False)
    passphrase: str = field(default="", repr=False)


@dataclass(frozen=True)
class StoredObject:
    data: bytes
    etag: str


@dataclass(frozen=True)
class BackupVersion:
    revision: str
    created_at: str
    sha256: str
    size: int
    encrypted: bool


@dataclass(frozen=True)
class BackupOverview:
    versions: tuple[BackupVersion, ...]
    local_digest: str
    remote_changed: bool
    local_changed: bool


def backup_due(configuration, last_success: datetime | None, now: datetime):
    if configuration.schedule == "off":
        return False
    if last_success is None:
        return True
    if configuration.schedule == "interval":
        return now.timestamp() >= last_success.timestamp() + configuration.interval_hours * 3600
    hour, minute = map(int, configuration.time.split(":"))
    local = now.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
    local = datetime.fromtimestamp(local.timestamp(), now.tzinfo)
    if configuration.schedule == "daily":
        if local > now:
            local -= timedelta(days=1)
    elif configuration.schedule == "weekly":
        local -= timedelta(days=(local.weekday() - configuration.weekday) % 7)
        if local > now:
            local -= timedelta(days=7)
    else:
        local = local.replace(day=min(configuration.month_day, calendar.monthrange(local.year, local.month)[1]))
        if local > now:
            first = local.replace(day=1) - timedelta(days=1)
            local = first.replace(day=min(configuration.month_day, first.day))
    return last_success.timestamp() < local.timestamp()
