"""Bounded local model metadata reads and atomic persistence."""

import json
import logging
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from worklogger.domain.local_model.models import LocalModelEntry
from worklogger.infrastructure.files import atomic_destination, file_fingerprint
from worklogger.infrastructure.local_model.catalog import catalog_entries, model_entry_from_mapping

_MAX_MANIFEST_BYTES = 1024 * 1024


class LocalModelMetadata:
    def __init__(self, models_dir: Path, *, bundled_catalog_path: Path | None, max_catalog_bytes: int):
        self._models_dir = models_dir
        self._bundled_catalog_path = bundled_catalog_path
        self._max_catalog_bytes = max_catalog_bytes
        self._catalog_cache = {}
        self._cache_lock = RLock()

    def load_catalog(self) -> list[LocalModelEntry]:
        entries = {}
        for entry in self.bundled_entries():
            entries.setdefault(entry.id, entry)
        for entry in self._read_catalog(self._models_dir / "catalog.json"):
            entries.setdefault(entry.id, entry)
        return list(entries.values())

    def bundled_entries(self) -> tuple[LocalModelEntry, ...]:
        if self._bundled_catalog_path is None:
            return ()
        return self._read_catalog(Path(self._bundled_catalog_path))

    def _read_catalog(self, path: Path) -> tuple[LocalModelEntry, ...]:
        with self._cache_lock:
            if not path.exists():
                self._catalog_cache.pop(path, None)
                return ()
            key = file_fingerprint(path.stat())
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

    def save_catalog(self, entries: list[LocalModelEntry], *, sync_manifest: bool = False,
                     available_model_id: str | None = None) -> None:
        path = self._models_dir / "catalog.json"
        with self._cache_lock:
            mappings = [asdict(entry) for entry in entries]
            for mapping in mappings:
                model_entry_from_mapping(mapping)
            if len({entry.id for entry in entries}) != len(entries):
                raise ValueError("local_model_catalog_invalid")
            content = _json_bytes({"models": mappings}, self._max_catalog_bytes, "local_model_catalog_too_large")
            manifest_path = self._models_dir / "manifest.json"
            manifest = None
            previous_manifest = None
            manifest_existed = False
            if sync_manifest or available_model_id is not None:
                manifest_existed = manifest_path.exists()
                previous_manifest = _read_json_list(manifest_path)
                records = self._manifest_records(entries, existing=previous_manifest)
                for record in records:
                    if record["id"] == available_model_id:
                        record["available"] = True
                manifest = _json_bytes(records, _MAX_MANIFEST_BYTES, "local_model_manifest_invalid")
            # Validate both documents before publication; the catalog is authoritative and commits last.
            manifest_written = False
            try:
                with atomic_destination(path) as temporary:
                    temporary.write_bytes(content)
                    if manifest is not None:
                        with atomic_destination(manifest_path) as pending:
                            pending.write_bytes(manifest)
                        manifest_written = True
            except BaseException:
                if manifest_written:
                    try:
                        if manifest_existed:
                            _write_json_atomic(manifest_path, previous_manifest)
                        else:
                            manifest_path.unlink(missing_ok=True)
                    except OSError as error:
                        logging.getLogger(__name__).error("local_model_manifest_restore_failed: %s", type(error).__name__)
                raise
            self._catalog_cache.pop(path, None)

    def sync_manifest(self, entries: list[LocalModelEntry]) -> None:
        _write_json_atomic(self._models_dir / "manifest.json", self._manifest_records(entries))

    def _manifest_records(self, entries: list[LocalModelEntry], *, existing: list[object] | None = None) -> list[dict]:
        path = self._models_dir / "manifest.json"
        manifest = {
            str(item.get("id", "")): item
            for item in (_read_json_list(path) if existing is None else existing)
            if isinstance(item, dict)
        }
        return [_manifest_record(entry, bool(manifest.get(entry.id, {}).get("available", False))) for entry in entries]

    def set_available(self, entry: LocalModelEntry, available: bool) -> None:
        path = self._models_dir / "manifest.json"
        updated = False
        next_items = []
        for item in _read_json_list(path):
            if not isinstance(item, dict):
                continue
            if item.get("id") == entry.id:
                item = _manifest_record(entry, available)
                updated = True
            next_items.append(item)
        if not updated:
            next_items.append(_manifest_record(entry, available))
        _write_json_atomic(path, next_items)


def _manifest_record(entry: LocalModelEntry, available: bool) -> dict[str, object]:
    return {"id": entry.id, "filename": entry.filename, "sha256": entry.sha256, "available": bool(available)}


def _read_json_list(path: Path) -> list[object]:
    if not path.exists():
        return []
    with path.open("rb") as stream:
        content = stream.read(_MAX_MANIFEST_BYTES + 1)
    if len(content) > _MAX_MANIFEST_BYTES:
        raise ValueError("local_model_manifest_invalid")
    data = json.loads(content.decode("utf-8"))
    if not isinstance(data, list):
        raise ValueError("local_model_manifest_invalid")
    return data


def _json_bytes(data: object, maximum: int, error_code: str) -> bytes:
    content = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(content) > maximum:
        raise ValueError(error_code)
    return content


def _write_json_atomic(path: Path, data: object) -> None:
    content = _json_bytes(data, _MAX_MANIFEST_BYTES, "local_model_manifest_invalid")
    with atomic_destination(path) as temporary:
        temporary.write_bytes(content)
