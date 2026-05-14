"""JSON-backed local model catalog and shared GGUF storage."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from worklogger.domain.local_model.models import LocalModelEntry, LocalModelFileStatus
from worklogger.domain.shared.errors import InfrastructureError, ValidationError
from worklogger.domain.shared.result import Result

CATALOG_FILENAME = "catalog.json"
MANIFEST_FILENAME = "manifest.json"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


UrlOpen = Callable[..., object]


class HttpRangeDownloader:
    def __init__(
        self,
        *,
        opener: UrlOpen | None = None,
        timeout_seconds: float = 30.0,
        chunk_size: int = 64 * 1024,
    ) -> None:
        self._opener = opener or urlopen
        self._timeout_seconds = timeout_seconds
        self._chunk_size = chunk_size

    def download(
        self,
        *,
        url: str,
        destination: Path,
        expected_sha256: str = "",
    ) -> Result[Path]:
        try:
            safe_url = safe_model_url(url)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temp_path = destination.with_suffix(destination.suffix + ".tmp")
            _download_to_temp(
                opener=self._opener,
                url=safe_url,
                destination=temp_path,
                timeout_seconds=self._timeout_seconds,
                chunk_size=self._chunk_size,
            )
            actual_sha = sha256_of_file(temp_path)
            expected = str(expected_sha256 or "").strip().lower()
            if expected and actual_sha != expected:
                temp_path.unlink(missing_ok=True)
                return Result.failure(
                    ValidationError(
                        "local_model_hash_mismatch",
                        "local_model_hash_mismatch",
                    )
                )
            shutil.move(str(temp_path), str(destination))
            return Result.success(destination)
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_download_failed",
                    "local_model_download_failed",
                    {"reason": str(exc)},
                )
            )


class JsonLocalModelStore:
    def __init__(
        self,
        models_dir: Path | str,
        *,
        remote_catalog_url: str | None = None,
        catalog_opener: UrlOpen | None = None,
        downloader: HttpRangeDownloader | None = None,
        max_catalog_bytes: int = 1024 * 1024,
    ) -> None:
        self._models_dir = Path(models_dir)
        self._remote_catalog_url = remote_catalog_url
        self._catalog_opener = catalog_opener or urlopen
        self._downloader = downloader or HttpRangeDownloader()
        self._max_catalog_bytes = max_catalog_bytes

    def list_models(self) -> Result[tuple[LocalModelEntry, ...]]:
        try:
            return Result.success(tuple(self._load_catalog()))
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_catalog_failed",
                    "local_model_catalog_failed",
                    {"reason": str(exc)},
                )
            )

    def refresh_catalog(self) -> Result[tuple[LocalModelEntry, ...]]:
        if not self._remote_catalog_url:
            return self.list_models()
        try:
            remote = self._fetch_remote_catalog()
            local = [
                entry
                for entry in self._load_catalog()
                if entry.status in {"local", "preserved"}
            ]
            local_ids = {entry.id for entry in local}
            merged = [
                entry
                for entry in remote
                if entry.id not in local_ids
            ] + local
            self._save_catalog(merged)
            self._sync_manifest(merged)
            return Result.success(tuple(merged))
        except Exception:
            return self.list_models()

    def import_model(self, source: Path) -> Result[LocalModelEntry]:
        try:
            source = Path(source)
            if not source.is_file():
                return Result.failure(ValidationError("local_model_file_missing", "local_model_file_missing"))
            if source.suffix.lower() != ".gguf":
                return Result.failure(ValidationError("local_model_file_must_be_gguf", "local_model_file_must_be_gguf"))
            if source.stat().st_size <= 0:
                return Result.failure(ValidationError("local_model_file_empty", "local_model_file_empty"))
            self._models_dir.mkdir(parents=True, exist_ok=True)
            digest = sha256_of_file(source)
            filename = safe_model_filename(source.name)
            destination = self._unique_destination(filename, digest)
            if not destination.exists() or sha256_of_file(destination) != digest:
                shutil.copy2(source, destination)
            entry = LocalModelEntry(
                id=_safe_model_id(destination.stem, digest),
                display_name=source.stem,
                filename=destination.name,
                status="local",
                sha256=digest,
                estimated_size_mb=max(1, int(source.stat().st_size / 1_048_576)),
                description=f"Local model: {destination.name}",
            )
            catalog = [item for item in self._load_catalog() if item.id != entry.id]
            catalog.append(entry)
            self._save_catalog(catalog)
            self._set_manifest_available(entry, True)
            return Result.success(entry)
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_import_failed",
                    "local_model_import_failed",
                    {"reason": str(exc)},
                )
            )

    def download_model(self, model_id: str) -> Result[LocalModelEntry]:
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
        )
        if not downloaded.ok:
            return Result.failure(
                downloaded.error
                or InfrastructureError(
                    "local_model_download_failed",
                    "local_model_download_failed",
                )
            )
        self._set_manifest_available(entry.value, True)
        return entry

    def verify_model(self, model_id: str) -> Result[LocalModelFileStatus]:
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
            expected = str(entry.value.sha256 or "").strip().lower()
            if expected and sha256_of_file(path) != expected:
                return Result.success(
                    LocalModelFileStatus(model_id, available=True, verified=False, reason="local_model_hash_mismatch")
                )
            return Result.success(
                LocalModelFileStatus(model_id, available=True, verified=True, reason="")
            )
        except PermissionError:
            return Result.success(
                LocalModelFileStatus(model_id, available=True, verified=False, reason="local_model_permission_denied")
            )
        except Exception as exc:
            return Result.failure(
                InfrastructureError(
                    "local_model_verify_failed",
                    "local_model_verify_failed",
                    {"reason": str(exc)},
                )
            )

    def delete_model(self, model_id: str) -> Result[None]:
        entry = self._entry(model_id)
        if not entry.ok or entry.value is None:
            return Result.failure(entry.error or ValidationError("local_model_missing", "local_model_missing"))
        try:
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
                    {"reason": str(exc)},
                )
            )

    @property
    def models_dir(self) -> Path:
        return self._models_dir

    def _entry(self, model_id: str) -> Result[LocalModelEntry]:
        cleaned = str(model_id or "").strip()
        if not cleaned:
            return Result.failure(ValidationError("local_model_id_required", "local_model_id_required"))
        for entry in self._load_catalog():
            if entry.id == cleaned:
                return Result.success(entry)
        return Result.failure(ValidationError("local_model_missing", "local_model_missing"))

    def _catalog_path(self) -> Path:
        return self._models_dir / CATALOG_FILENAME

    def _manifest_path(self) -> Path:
        return self._models_dir / MANIFEST_FILENAME

    def _load_catalog(self) -> list[LocalModelEntry]:
        path = self._catalog_path()
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            raw_entries = data.get("models", [])
        else:
            raw_entries = data
        if not isinstance(raw_entries, list):
            raise ValueError("local_model_catalog_invalid")
        return [_entry_from_json(item) for item in raw_entries]

    def _save_catalog(self, entries: list[LocalModelEntry]) -> None:
        self._models_dir.mkdir(parents=True, exist_ok=True)
        data = {"models": [asdict(entry) for entry in entries]}
        _write_json_atomic(self._catalog_path(), data)

    def _fetch_remote_catalog(self) -> list[LocalModelEntry]:
        request = Request(
            safe_model_url(str(self._remote_catalog_url)),
            headers={"User-Agent": "WorkLogger"},
        )
        with self._catalog_opener(request, timeout=15.0) as response:
            raw = response.read(self._max_catalog_bytes + 1)
        if len(raw) > self._max_catalog_bytes:
            raise ValueError("local_model_catalog_too_large")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ValueError("local_model_catalog_invalid")
        return [_entry_from_json(item) for item in data["models"]]

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

    def _unique_destination(self, filename: str, digest: str) -> Path:
        destination = self._resolve(filename)
        if not destination.exists():
            return destination
        if sha256_of_file(destination) == digest:
            return destination
        return self._resolve(f"{Path(filename).stem}-{digest[:8]}.gguf")


def safe_model_filename(filename: str) -> str:
    name = str(filename or "").strip()
    win_path = PureWindowsPath(name)
    if (
        not name
        or "/" in name
        or "\\" in name
        or ":" in name
        or Path(name).is_absolute()
        or win_path.is_absolute()
        or win_path.drive
        or name in {".", ".."}
        or ".." in Path(name).parts
        or any(ord(character) < 32 for character in name)
        or not name.lower().endswith((".gguf", ".gguf.tmp"))
    ):
        raise ValueError("local_model_filename_invalid")
    return name


def safe_model_url(url: str) -> str:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("local_model_url_invalid")
    host = parsed.hostname.strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("local_model_url_invalid")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host):
            raise ValueError("local_model_url_invalid")
        return raw
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError("local_model_url_invalid")
    return raw


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_from_json(raw: object) -> LocalModelEntry:
    if not isinstance(raw, dict):
        raise ValueError("local_model_catalog_invalid")
    model_id = str(raw.get("id") or "").strip()
    if not _ID_RE.fullmatch(model_id):
        raise ValueError("local_model_catalog_invalid")
    sha = str(raw.get("sha256") or "").strip().lower()
    if sha and not _SHA_RE.fullmatch(sha):
        raise ValueError("local_model_catalog_invalid")
    download_url = str(raw.get("download_url") or "").strip()
    if download_url:
        download_url = safe_model_url(download_url)
    return LocalModelEntry(
        id=model_id,
        display_name=str(raw.get("display_name") or model_id).strip() or model_id,
        filename=safe_model_filename(str(raw.get("filename") or "")),
        status=str(raw.get("status") or "stable").strip() or "stable",
        sha256=sha,
        download_url=download_url,
        estimated_size_mb=max(0, _int(raw.get("estimated_size_mb"))),
        min_ram_gb=max(0, _int(raw.get("min_ram_gb"))),
        context_length=max(1, _int(raw.get("context_length"), 8192)),
        max_output_tokens=max(1, _int(raw.get("max_output_tokens"), 2048)),
        description=str(raw.get("description") or "").strip(),
    )


def _safe_model_id(stem: str, digest: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(stem or "model")).strip("._-")
    return f"local_{cleaned or 'model'}_{digest[:8]}"


def _int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _read_json_list(path: Path) -> list[object]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def _write_json_atomic(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.move(str(temp), str(path))


def _download_to_temp(
    *,
    opener: UrlOpen,
    url: str,
    destination: Path,
    timeout_seconds: float,
    chunk_size: int,
) -> None:
    resume_from = destination.stat().st_size if destination.exists() else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from > 0 else {}
    request = Request(url, headers=headers)
    try:
        response = opener(request, timeout=timeout_seconds)
    except HTTPError as exc:
        if exc.code == 416 and destination.exists():
            destination.unlink(missing_ok=True)
            response = opener(Request(url), timeout=timeout_seconds)
        else:
            raise
    except URLError:
        raise
    mode = "ab" if resume_from > 0 else "wb"
    with response:
        with destination.open(mode) as handle:
            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                handle.write(chunk)
