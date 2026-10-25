"""Bounded local model metadata reads and atomic persistence."""

import json
from dataclasses import asdict
from pathlib import Path
from threading import RLock

from worklogger.domain.local_model.models import LocalModelEntry
from worklogger.infrastructure.files import atomic_destination, file_fingerprint
from worklogger.infrastructure.local_model.catalog import catalog_entries


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

    def save_catalog(self, entries: list[LocalModelEntry]) -> None:
        path = self._models_dir / "catalog.json"
        with self._cache_lock:
            _write_json_atomic(path, {"models": [asdict(entry) for entry in entries]})
            self._catalog_cache.pop(path, None)

    def sync_manifest(self, entries: list[LocalModelEntry]) -> None:
        path = self._models_dir / "manifest.json"
        manifest = {
            str(item.get("id", "")): item
            for item in _read_json_list(path)
            if isinstance(item, dict)
        }
        for entry in entries:
            existing = manifest.get(entry.id, {})
            manifest[entry.id] = _manifest_record(entry, bool(existing.get("available", False)))
        _write_json_atomic(path, list(manifest.values()))

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
        content = stream.read(1024 * 1024 + 1)
    if len(content) > 1024 * 1024:
        raise ValueError("local_model_manifest_invalid")
    data = json.loads(content.decode("utf-8"))
    return data if isinstance(data, list) else []


def _write_json_atomic(path: Path, data: object) -> None:
    with atomic_destination(path) as temporary:
        temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
