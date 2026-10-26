"""Shared GGUF file operations coordinated with local model metadata."""

from __future__ import annotations

import hashlib
import shutil
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import RLock
from urllib.request import Request

from worklogger.domain.local_model.models import LocalModelEntry, LocalModelFileStatus, is_sha256_digest
from worklogger.domain.shared.errors import CancellationError, InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result
from worklogger.infrastructure.files import file_fingerprint
from worklogger.infrastructure.http import https_opener
from worklogger.infrastructure.local_model.catalog import model_entry_from_mapping
from worklogger.infrastructure.local_model.download import HttpRangeDownloader, UrlOpen
from worklogger.infrastructure.local_model.files import check_download_cancelled, has_gguf_header, safe_model_filename, safe_model_url, sha256_of_file
from worklogger.infrastructure.local_model.metadata import LocalModelMetadata


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
        self._metadata = LocalModelMetadata(self._models_dir, bundled_catalog_path=bundled_catalog_path,
                                            max_catalog_bytes=self._max_catalog_bytes)
        self._verified_files = {}
        self._cache_lock = RLock()
        self._metadata_lock = RLock()

    def list_models(self) -> Result[tuple[LocalModelEntry, ...]]:
        try:
            return Result.success(tuple(self._metadata.load_catalog()))
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
                existing = self._metadata.load_catalog()
                bundled = self._metadata.bundled_entries()
                bundled_ids = {entry.id for entry in bundled}
                remote_entries = {entry.id: entry for entry in remote}
                local = []
                for entry in existing:
                    if entry.id in bundled_ids:
                        continue
                    if entry.status == "local" and not entry.download_url:
                        local.append(entry)
                        continue
                    incoming = remote_entries.get(entry.id)
                    verified = self.verify_model(entry.id)
                    if verified.ok and verified.value.verified:
                        if incoming and (incoming.filename, incoming.sha256) == (entry.filename, entry.sha256):
                            local.append(incoming)
                        else:
                            local.append(replace(entry, status="preserved"))
                protected_ids = {entry.id for entry in (*bundled, *local)}
                protected_files = {entry.filename.casefold() for entry in (*bundled, *local)}
                merged = list(bundled) + [entry for entry in remote if entry.id not in protected_ids
                    and entry.filename.casefold() not in protected_files] + [entry for entry in local
                        if entry.id not in bundled_ids]
                self._metadata.save_catalog(merged, sync_manifest=True)
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
            if source.stat().st_size > shutil.disk_usage(self._models_dir).free:
                return Result.failure(ValidationError("local_model_disk_full", "local_model_disk_full"))
            filename = safe_model_filename(source.name)
            with tempfile.TemporaryDirectory(prefix=".import-", dir=self._models_dir) as directory:
                temporary = Path(directory) / filename
                copied = hashlib.sha256()
                with source.open("rb") as reader, temporary.open("xb") as writer:
                    before = os.fstat(reader.fileno())
                    remaining = before.st_size
                    next_space_check = 0
                    for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                        check_download_cancelled(is_cancelled)
                        if next_space_check <= 0:
                            if remaining > shutil.disk_usage(self._models_dir).free:
                                raise ValueError("local_model_disk_full")
                            next_space_check = 8 * 1024 * 1024
                        writer.write(chunk)
                        copied.update(chunk)
                        remaining -= len(chunk)
                        next_space_check -= len(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                    after = os.fstat(reader.fileno())
                    if file_fingerprint(before) != file_fingerprint(after):
                        raise ValueError("local_model_hash_mismatch")
                check_download_cancelled(is_cancelled)
                if not has_gguf_header(temporary):
                    raise ValueError("local_model_file_must_be_gguf")
                digest = copied.hexdigest()
                with self._metadata_lock:
                    catalog = self._metadata.load_catalog()
                    destination, existing_verified = self._unique_destination(filename, digest, catalog=catalog,
                                                                               is_cancelled=is_cancelled)
                    check_download_cancelled(is_cancelled)
                    if not existing_verified:
                        os.replace(temporary, destination)
                    entry = next((item for item in catalog if item.sha256 == digest
                                  and self._resolve(item.filename) == destination), None)
                    if entry is None:
                        entry = LocalModelEntry(
                            id=_safe_model_id(destination.stem, digest), display_name=source.stem,
                            filename=destination.name, status="local", sha256=digest,
                            estimated_size_mb=max(1, int(destination.stat().st_size / 1_048_576)),
                            description=destination.name,
                        )
                        self._metadata.save_catalog([item for item in catalog if item.id != entry.id] + [entry])
                    self._metadata.set_available(entry, True)
            return Result.success(entry)
        except InterruptedError:
            return Result.failure(CancellationError("job_cancelled", "job_cancelled"))
        except ValueError as error:
            if str(error) == "local_model_disk_full":
                return Result.failure(ValidationError("local_model_disk_full", "local_model_disk_full"))
            return Result.failure(InfrastructureError("local_model_import_failed", "local_model_import_failed"))
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
                self._metadata.set_available(entry.value, True)
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
            fingerprint = file_fingerprint(path.stat())
            with self._cache_lock:
                cached = self._verified_files.get(path)
                actual = cached[2] if cached is not None and cached[:2] == (fingerprint, expected) else None
            if actual is None:
                actual = sha256_of_file(path, is_cancelled=is_cancelled)
                if file_fingerprint(path.stat()) != fingerprint:
                    return Result.success(LocalModelFileStatus(model_id, True, False, "local_model_hash_mismatch"))
                with self._cache_lock:
                    self._verified_files[path] = (fingerprint, expected, actual)
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
                path = self._resolve(entry.value.filename)
                catalog = self._metadata.load_catalog()
                shared = any(item.id != entry.value.id and self._resolve(item.filename) == path for item in catalog)
                if entry.value.status in {"local", "preserved"}:
                    catalog = [item for item in catalog if item.id != entry.value.id]
                    self._metadata.save_catalog(catalog)
                if not shared:
                    path.unlink(missing_ok=True)
                    with self._cache_lock:
                        self._verified_files.pop(path, None)
                self._metadata.set_available(entry.value, False)
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
        entries = {}
        for item in data["models"]:
            entry = model_entry_from_mapping(item)
            if entry.status in {"local", "preserved"}:
                entry = replace(entry, status="stable")
            entries.setdefault(entry.id, entry)
        return list(entries.values())

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

    def _unique_destination(self, filename: str, digest: str, *, catalog=(), is_cancelled=None) -> tuple[Path, bool]:
        for name in (filename, f"{Path(filename).stem}-{digest[:8]}.gguf"):
            destination = self._resolve(name)
            owners = [entry for entry in catalog if self._resolve(entry.filename) == destination]
            if owners and not any(entry.sha256 == digest for entry in owners):
                continue
            if not destination.exists():
                return destination, False
            if sha256_of_file(destination, is_cancelled=is_cancelled) == digest:
                return destination, True
        raise ValueError("local_model_hash_mismatch")


def _safe_model_id(stem: str, digest: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(stem or "model")).strip("._-")
    return f"local_{cleaned or 'model'}_{digest[:8]}"
