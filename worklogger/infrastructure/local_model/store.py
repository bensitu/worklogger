"""JSON-backed local model catalog and shared GGUF storage."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from threading import RLock
from urllib.request import Request

from worklogger.domain.local_model.models import LocalModelEntry, LocalModelFileStatus, is_sha256_digest
from worklogger.domain.shared.errors import CancellationError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.files import atomic_destination
from worklogger.infrastructure.http import https_opener

CATALOG_FILENAME = "catalog.json"
MANIFEST_FILENAME = "manifest.json"




from worklogger.infrastructure.local_model.catalog import bundled_model_catalog_path as bundled_model_catalog_path
from worklogger.infrastructure.local_model.catalog import catalog_entries
from worklogger.infrastructure.local_model.download import HttpRangeDownloader, UrlOpen
from worklogger.infrastructure.local_model.files import check_download_cancelled, has_gguf_header, safe_model_filename, safe_model_url, sha256_of_file


class JsonLocalModelStore:
    def __init__(
        self,
        models_dir: Path | str,
        *,
        remote_catalog_url: str | None = None,
        catalog_opener: UrlOpen | None = None,
        downloader: HttpRangeDownloader | None = None,
        max_catalog_bytes: int = 1024 * 1024,
        catalog_timeout_seconds: float = 15.0,
        bundled_catalog_path: Path | None = None,
    ) -> None:
        self._models_dir = Path(models_dir)
        self._remote_catalog_url = remote_catalog_url
        self._catalog_opener = catalog_opener or https_opener(public_only=True)
        self._downloader = downloader or HttpRangeDownloader()
        self._max_catalog_bytes = int(max_catalog_bytes)
        self._catalog_timeout_seconds = float(catalog_timeout_seconds)
        if (self._max_catalog_bytes < 1 or not math.isfinite(self._catalog_timeout_seconds)
                or self._catalog_timeout_seconds <= 0):
            raise ValueError("local_model_catalog_invalid")
        self._bundled_catalog_path = bundled_catalog_path
        self._verified_files = {}
        self._catalog_cache = {}
        self._cache_lock = RLock()
        self._metadata_lock = RLock()

    def list_models(self) -> Result[tuple[LocalModelEntry, ...]]:
        try:
            return Result.success(tuple(self._load_catalog()))
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_catalog_failed",
                    "local_model_catalog_failed",
                    {"reason": type(exc).__name__},
                )
            )

    def refresh_catalog(self) -> Result[tuple[LocalModelEntry, ...]]:
        if not self._remote_catalog_url:
            return self.list_models()
        try:
            remote = self._fetch_remote_catalog()
            with self._metadata_lock:
                local = [entry for entry in self._load_catalog() if entry.status in {"local", "preserved"}]
                bundled = self._load_catalog_file(Path(self._bundled_catalog_path)) if self._bundled_catalog_path is not None else ()
                protected_ids = {entry.id for entry in (*bundled, *local)}
                protected_files = {entry.filename.casefold() for entry in (*bundled, *local)}
                merged = list(bundled) + [entry for entry in remote if entry.id not in protected_ids
                    and entry.filename.casefold() not in protected_files] + [entry for entry in local
                        if entry.id not in {item.id for item in bundled}]
                self._save_catalog(merged)
                self._sync_manifest(merged)
                return self.list_models()
        except Exception:
            return Result.failure(InfrastructureError("local_model_catalog_failed", "local_model_catalog_failed"))

    def import_model(self, source: Path, *, is_cancelled=None) -> Result[LocalModelEntry]:
        try:
            check_download_cancelled(is_cancelled)
            source = Path(source)
            if not source.is_file():
                return Result.failure(ValidationError("local_model_file_missing", "local_model_file_missing"))
            if source.suffix.lower() != ".gguf":
                return Result.failure(ValidationError("local_model_file_must_be_gguf", "local_model_file_must_be_gguf"))
            if source.stat().st_size <= 0:
                return Result.failure(ValidationError("local_model_file_empty", "local_model_file_empty"))
            if not has_gguf_header(source):
                return Result.failure(ValidationError("local_model_file_must_be_gguf", "local_model_file_must_be_gguf"))
            self._models_dir.mkdir(parents=True, exist_ok=True)
            filename = safe_model_filename(source.name)
            with tempfile.TemporaryDirectory(prefix=".import-", dir=self._models_dir) as directory:
                temporary = Path(directory) / filename
                copied = hashlib.sha256()
                with source.open("rb") as reader, temporary.open("xb") as writer:
                    before = os.fstat(reader.fileno())
                    for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                        check_download_cancelled(is_cancelled)
                        writer.write(chunk)
                        copied.update(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                    after = os.fstat(reader.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                        raise ValueError("local_model_hash_mismatch")
                check_download_cancelled(is_cancelled)
                if not has_gguf_header(temporary):
                    raise ValueError("local_model_file_must_be_gguf")
                digest = copied.hexdigest()
                with self._metadata_lock:
                    catalog = self._load_catalog()
                    destination, existing_verified = self._unique_destination(filename, digest, is_cancelled=is_cancelled)
                    check_download_cancelled(is_cancelled)
                    if not existing_verified:
                        os.replace(temporary, destination)
                    entry = LocalModelEntry(
                        id=_safe_model_id(destination.stem, digest), display_name=source.stem,
                        filename=destination.name, status="local", sha256=digest,
                        estimated_size_mb=max(1, int(destination.stat().st_size / 1_048_576)),
                        description=destination.name,
                    )
                    self._save_catalog([item for item in catalog if item.id != entry.id] + [entry])
                    self._set_manifest_available(entry, True)
            return Result.success(entry)
        except InterruptedError:
            return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_import_failed",
                    "local_model_import_failed",
                    {"reason": type(exc).__name__},
                )
            )

    def download_model(self, model_id: str, *, is_cancelled: Callable[[], bool] | None = None, progress=None) -> Result[LocalModelEntry]:
        entry = self._entry(model_id)
        if not entry.ok or entry.value is None:
            return Result.failure(entry.error or ValidationError("local_model_missing", "local_model_missing"))
        if not entry.value.download_url:
            return Result.failure(
                ValidationError(
                    "local_model_download_url_missing",
                    "local_model_download_url_missing",
                )
            )
        try:
            destination = self._resolve(entry.value.filename)
        except ValueError as exc:
            return Result.failure(ValidationError(str(exc), str(exc)))
        downloaded = self._downloader.download(
            url=entry.value.download_url,
            destination=destination,
            expected_sha256=entry.value.sha256,
            is_cancelled=is_cancelled,
            **({"progress": progress} if progress is not None else {}),
        )
        if not downloaded.ok:
            return Result.failure(
                downloaded.error
                or InfrastructureError(
                    "local_model_download_failed",
                    "local_model_download_failed",
                )
            )
        try:
            with self._metadata_lock:
                self._set_manifest_available(entry.value, True)
        except Exception:
            return Result.failure(InfrastructureError("local_model_catalog_failed", "local_model_catalog_failed"))
        return entry

    def verify_model(self, model_id: str, *, is_cancelled=None) -> Result[LocalModelFileStatus]:
        entry = self._entry(model_id)
        if not entry.ok or entry.value is None:
            return Result.failure(entry.error or ValidationError("local_model_missing", "local_model_missing"))
        try:
            path = self._resolve(entry.value.filename)
            if not path.exists() or not path.is_file():
                return Result.success(
                    LocalModelFileStatus(model_id, available=False, verified=False, reason="local_model_missing")
                )
            if path.stat().st_size <= 0:
                return Result.success(
                    LocalModelFileStatus(model_id, available=True, verified=False, reason="local_model_empty")
                )
            if not has_gguf_header(path):
                return Result.success(LocalModelFileStatus(model_id, True, False, "local_model_file_must_be_gguf"))
            expected = str(entry.value.sha256 or "").strip().lower()
            if not is_sha256_digest(expected):
                return Result.success(LocalModelFileStatus(model_id, available=True, verified=False, reason="local_model_hash_required"))
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, expected)
            with self._cache_lock:
                actual = self._verified_files.get(key)
            if actual is None:
                actual = sha256_of_file(path, is_cancelled=is_cancelled)
                current = path.stat()
                if (current.st_mtime_ns, current.st_ctime_ns, current.st_size) != key[1:4]:
                    return Result.success(LocalModelFileStatus(model_id, True, False, "local_model_hash_mismatch"))
                with self._cache_lock:
                    self._verified_files = {old: digest for old, digest in self._verified_files.items() if old[0] != str(path)}
                    self._verified_files[key] = actual
            if actual != expected:
                return Result.success(
                    LocalModelFileStatus(model_id, available=True, verified=False, reason="local_model_hash_mismatch")
                )
            return Result.success(
                LocalModelFileStatus(model_id, available=True, verified=True, reason="")
            )
        except InterruptedError:
            return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
        except PermissionError:
            return Result.success(
                LocalModelFileStatus(model_id, available=True, verified=False, reason="local_model_permission_denied")
            )
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_verify_failed",
                    "local_model_verify_failed",
                    {"reason": type(exc).__name__},
                )
            )

    def delete_model(self, model_id: str) -> Result[None]:
        entry = self._entry(model_id)
        if not entry.ok or entry.value is None:
            return Result.failure(entry.error or ValidationError("local_model_missing", "local_model_missing"))
        try:
            with self._metadata_lock:
                self._resolve(entry.value.filename).unlink(missing_ok=True)
                catalog = self._load_catalog()
                if entry.value.status in {"local", "preserved"}:
                    catalog = [item for item in catalog if item.id != entry.value.id]
                    self._save_catalog(catalog)
                self._set_manifest_available(entry.value, False)
            return Result.success(None)
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_delete_failed",
                    "local_model_delete_failed",
                    {"reason": type(exc).__name__},
                )
            )

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    def model_path(self, model_id: str) -> Path:
        entry = self._entry(model_id)
        if not entry.ok or entry.value is None:
            raise ValueError("local_model_missing")
        return self._resolve(entry.value.filename)

    def _entry(self, model_id: str) -> Result[LocalModelEntry]:
        cleaned = str(model_id or "").strip()
        if not cleaned:
            return Result.failure(ValidationError("local_model_id_required", "local_model_id_required"))
        catalog = self.list_models()
        if not catalog.ok:
            return Result.failure(catalog.error)
        for entry in catalog.value or ():
            if entry.id == cleaned:
                return Result.success(entry)
        return Result.failure(ValidationError("local_model_missing", "local_model_missing"))

    def _catalog_path(self) -> Path:
        return self._models_dir / CATALOG_FILENAME

    def _manifest_path(self) -> Path:
        return self._models_dir / MANIFEST_FILENAME

    def _load_catalog(self) -> list[LocalModelEntry]:
        entries = {}
        paths = [self._bundled_catalog_path, self._catalog_path()]
        for path in paths:
            if path is not None:
                for entry in self._load_catalog_file(Path(path)):
                    entries.setdefault(entry.id, entry)
        return list(entries.values())

    def _load_catalog_file(self, path: Path) -> tuple[LocalModelEntry, ...]:
        with self._cache_lock:
            if not path.exists():
                self._catalog_cache.pop(path, None)
                return ()
            stat = path.stat()
            key = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
            cached = self._catalog_cache.get(path)
            if cached is not None and cached[0] == key:
                return cached[1]
            with path.open("rb") as source:
                raw = source.read(self._max_catalog_bytes + 1)
            if len(raw) > self._max_catalog_bytes:
                raise ValueError("local_model_catalog_too_large")
            data = json.loads(raw.decode("utf-8"))
            raw_entries = data.get("models") if isinstance(data, dict) else data
            if not isinstance(raw_entries, list):
                raise ValueError("local_model_catalog_invalid")
            entries = tuple(catalog_entries(raw_entries))
            self._catalog_cache[path] = (key, entries)
            return entries

    def _save_catalog(self, entries: list[LocalModelEntry]) -> None:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        data = {"models": [asdict(entry) for entry in entries]}
        _write_json_atomic(self._catalog_path(), data)

    def _fetch_remote_catalog(self) -> list[LocalModelEntry]:
        request = Request(
            safe_model_url(str(self._remote_catalog_url)),
            headers={"User-Agent": "WorkLogger"},
        )
        with self._catalog_opener(request, timeout=self._catalog_timeout_seconds) as response:
            raw = response.read(self._max_catalog_bytes + 1)
        if len(raw) > self._max_catalog_bytes:
            raise ValueError("local_model_catalog_too_large")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ValueError("local_model_catalog_invalid")
        return catalog_entries(data["models"])

    def _sync_manifest(self, entries: list[LocalModelEntry]) -> None:
        manifest = {
            str(item.get("id", "")): item
            for item in _read_json_list(self._manifest_path())
            if isinstance(item, dict)
        }
        for entry in entries:
            existing = manifest.get(entry.id, {})
            manifest[entry.id] = {
                "id": entry.id,
                "filename": entry.filename,
                "sha256": entry.sha256,
                "available": bool(existing.get("available", False)),
            }
        _write_json_atomic(self._manifest_path(), list(manifest.values()))

    def _set_manifest_available(self, entry: LocalModelEntry, available: bool) -> None:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        manifest = _read_json_list(self._manifest_path())
        updated = False
        next_items: list[dict[str, object]] = []
        for item in manifest:
            if not isinstance(item, dict):
                continue
            if item.get("id") == entry.id:
                item = {
                    "id": entry.id,
                    "filename": entry.filename,
                    "sha256": entry.sha256,
                    "available": bool(available),
                }
                updated = True
            next_items.append(item)
        if not updated:
            next_items.append(
                {
                    "id": entry.id,
                    "filename": entry.filename,
                    "sha256": entry.sha256,
                    "available": bool(available),
                }
            )
        _write_json_atomic(self._manifest_path(), next_items)

    def _resolve(self, filename: str) -> Path:
        base = self._models_dir.resolve(strict=False)
        safe_name = safe_model_filename(filename)
        resolved = (base / safe_name).resolve(strict=False)
        common = os.path.commonpath(
            [
                os.path.normcase(str(base)),
                os.path.normcase(str(resolved)),
            ]
        )
        if common != os.path.normcase(str(base)):
            raise ValueError("local_model_filename_invalid")
        return resolved

    def _unique_destination(self, filename: str, digest: str, *, is_cancelled=None) -> tuple[Path, bool]:
        destination = self._resolve(filename)
        if not destination.exists():
            return destination, False
        if sha256_of_file(destination, is_cancelled=is_cancelled) == digest:
            return destination, True
        candidate = self._resolve(f"{Path(filename).stem}-{digest[:8]}.gguf")
        if candidate.exists():
            if sha256_of_file(candidate, is_cancelled=is_cancelled) != digest:
                raise ValueError("local_model_hash_mismatch")
            return candidate, True
        return candidate, False


def _safe_model_id(stem: str, digest: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(stem or "model")).strip("._-")
    return f"local_{cleaned or 'model'}_{digest[:8]}"


def _read_json_list(path: Path) -> list[object]:
    if not path.exists():
        return []
    with path.open("rb") as stream:
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("local_model_manifest_invalid")
    data = json.loads(content.decode("utf-8"))
    return data if isinstance(data, list) else []


def _write_json_atomic(path: Path, data: object) -> None:
    with atomic_destination(path) as temporary:
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
