"""Version-checked personal cloud uploads and guarded account restoration."""

from dataclasses import asdict, dataclass
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import json
import re
from threading import RLock
from uuid import uuid4

from worklogger.domain.cloud_backup import BackupCredentials, BackupOverview, BackupVersion, LocalBackupOverview, MAX_BACKUP_BYTES
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.app.cloud_backup_ports import BackupArchive, BackupObjectStore, PersonalDataStore


@dataclass(frozen=True)
class BackupTransfer:
    revision: str
    recovery_path: str = ""
    retention_pending: bool = False


def _result(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self._lock:
            try:
                return Result.success(method(self, *args, **kwargs))
            except ValueError as error:
                code = str(error)
                if not code.startswith(("cloud_", "credential_")):
                    code = "cloud_backup_invalid"
                return Result.failure(ValidationError(code, code))
            except Exception:
                return Result.failure(InfrastructureError("cloud_operation_failed", "cloud_operation_failed"))
    return run


def _digest(data):
    return hashlib.sha256(data).hexdigest()


class CloudBackupService:
    def __init__(self, *, configuration, personal_data: PersonalDataStore, archive: BackupArchive,
                 store_factory: Callable[..., BackupObjectStore], recovery_store,
                 now=lambda: datetime.now(timezone.utc)):
        self.configuration, self.personal_data, self.archive = configuration, personal_data, archive
        self.store_factory, self.recovery_store, self.now = store_factory, recovery_store, now
        self._lock = RLock()

    def _context(self):
        configuration = self.configuration.load()
        if configuration is None:
            raise ValueError("cloud_not_configured")
        configuration.validate()
        credentials = self.configuration.secrets()
        if not credentials.username or not credentials.password:
            raise ValueError("cloud_credentials_invalid")
        return configuration, credentials, self.store_factory(configuration, credentials)

    @_result
    def settings(self):
        configuration = self.configuration.load()
        return configuration, self.configuration.secrets() if configuration is not None else BackupCredentials(), self.configuration.state()

    @_result
    def configure(self, configuration, credentials):
        self.configuration.save(configuration, credentials)

    @_result
    def test_connection(self):
        _configuration, _credentials, store = self._context()
        store.test_connection()

    def _head(self, store):
        head = store.get("head.json", limit=256 * 1024)
        if head is None:
            return (), None
        if not head.etag or head.etag.startswith("W/"):
            raise ValueError("cloud_conditional_unsupported")
        try:
            value = json.loads(head.data)
            if set(value) != {"format", "versions"} or value["format"] != 1 or not isinstance(value["versions"], list):
                raise ValueError("cloud_backup_invalid")
            versions = tuple(BackupVersion(**row) for row in value["versions"])
            if not versions or len(versions) > 200 or len({row.revision for row in versions}) != len(versions):
                raise ValueError("cloud_backup_invalid")
            for row in versions:
                stamp = datetime.fromisoformat(row.created_at)
                if (not re.fullmatch(r"[0-9a-f]{32}", row.revision) or not re.fullmatch(r"[0-9a-f]{64}", row.sha256)
                        or type(row.size) is not int or not 1 <= row.size <= MAX_BACKUP_BYTES
                        or type(row.encrypted) is not bool or stamp.tzinfo is None):
                    raise ValueError("cloud_backup_invalid")
            return versions, head.etag
        except (TypeError, KeyError, AttributeError, RecursionError):
            raise ValueError("cloud_backup_invalid") from None

    @_result
    def overview(self):
        _configuration, _credentials, store = self._context()
        versions, _etag = self._head(store)
        state = self.configuration.state()
        digest = _digest(self.personal_data.capture())
        latest = versions[0].revision if versions else ""
        return BackupOverview(versions, digest, latest != state.get("remote_revision", ""),
                              digest != state.get("local_digest", ""))

    @_result
    def upload(self, *, expected_revision=None, force=False):
        configuration, credentials, store = self._context()
        versions, etag = self._head(store)
        state = self.configuration.state()
        latest = versions[0].revision if versions else ""
        expected = state.get("remote_revision", "") if expected_revision is None else expected_revision
        if latest != expected or (latest != state.get("remote_revision", "") and not force):
            raise ValueError("cloud_conflict")
        store.test_connection()
        document = self.personal_data.capture()
        content = self.archive.encode(document, encrypted=configuration.encrypted, passphrase=credentials.passphrase)
        now = self.now()
        version = BackupVersion(uuid4().hex, now.isoformat(), _digest(content), len(content), configuration.encrypted)
        store.put("objects/" + version.revision + ".wlbackup", content, expected_etag=None)
        cutoff = now - timedelta(days=configuration.keep_days)
        kept = (version,) + tuple(row for row in versions if datetime.fromisoformat(row.created_at) >= cutoff)[:configuration.keep_count - 1]
        head = json.dumps({"format": 1, "versions": [asdict(row) for row in kept]}, separators=(",", ":")).encode()
        store.put("head.json", head, expected_etag=etag)
        pending = set(state.get("pending_deletions", ())) | {row.revision for row in versions if row not in kept}
        remaining = []
        for revision in sorted(pending):
            if not re.fullmatch(r"[0-9a-f]{32}", revision) or revision in {row.revision for row in kept}:
                continue
            try:
                store.delete("objects/" + revision + ".wlbackup")
            except Exception:
                remaining.append(revision)
        self.configuration.save_state({**state, "remote_revision": version.revision, "local_digest": _digest(document),
            "last_success": now.isoformat(), "last_error": "", "pending_deletions": remaining})
        return BackupTransfer(version.revision, retention_pending=bool(remaining))

    @_result
    def download(self, revision, *, expected_revision, expected_local_digest, force=False, passphrase=None):
        configuration, credentials, store = self._context()
        versions, etag = self._head(store)
        if not versions or versions[0].revision != expected_revision:
            raise ValueError("cloud_conflict")
        selected = next((row for row in versions if row.revision == revision), None)
        if selected is None:
            raise ValueError("cloud_backup_missing")
        state = self.configuration.state()
        if expected_local_digest != state.get("local_digest", "") and not force:
            raise ValueError("cloud_local_changed")
        found = store.get("objects/" + selected.revision + ".wlbackup", limit=MAX_BACKUP_BYTES)
        if found is None or len(found.data) != selected.size or _digest(found.data) != selected.sha256:
            raise ValueError("cloud_backup_invalid")
        document = self.archive.decode(found.data, passphrase=credentials.passphrase if passphrase is None else passphrase)
        _current, current_etag = self._head(store)
        if current_etag != etag:
            raise ValueError("cloud_conflict")
        return self._restore_document(document, expected_local_digest=expected_local_digest,
            encrypted=configuration.encrypted, passphrase=credentials.passphrase, revision=selected.revision,
            sync_state={**state, "remote_revision": versions[0].revision, "last_restore": self.now().isoformat(), "last_error": ""})

    def _restore_document(self, document, *, expected_local_digest, encrypted, passphrase, sync_state, revision=""):
        recovery_path = ""
        def before_replace(previous):
            nonlocal recovery_path
            recovery = self.archive.encode(previous, encrypted=encrypted, passphrase=passphrase)
            recovery_path = str(self.recovery_store(recovery))
        self.personal_data.restore(document, expected_digest=expected_local_digest, before_replace=before_replace,
            sync_state=sync_state)
        return BackupTransfer(revision, recovery_path)

    @_result
    def preview_local(self, path):
        content = self.recovery_store.read(path)
        return LocalBackupOverview(_digest(self.personal_data.capture()), _digest(content))

    @_result
    def restore_local(self, path, *, expected_local_digest, expected_archive_digest, passphrase=""):
        content = self.recovery_store.read(path)
        if _digest(content) != expected_archive_digest:
            raise ValueError("cloud_local_changed")
        credentials = self.configuration.secrets() if not passphrase else BackupCredentials(passphrase=passphrase)
        document = self.archive.decode(content, passphrase=passphrase or credentials.passphrase)
        configuration = self.configuration.load()
        encrypted = configuration.encrypted if configuration is not None else True
        state = self.configuration.state()
        return self._restore_document(document, expected_local_digest=expected_local_digest,
            encrypted=encrypted, passphrase=passphrase or credentials.passphrase,
            sync_state={**state, "remote_revision": "", "last_restore": self.now().isoformat(), "last_error": "cloud_local_changed"})

    @_result
    def record_failure(self, code):
        state = self.configuration.state()
        self.configuration.save_state({**state, "last_attempt": self.now().isoformat(), "last_error": code})
