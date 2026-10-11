"""Model catalog decoding independent of downloads and managed file storage."""

from __future__ import annotations

import re
from pathlib import Path

from worklogger.domain.local_model.models import LocalModelEntry, is_sha256_digest
from worklogger.infrastructure.local_model.files import safe_model_filename, safe_model_url

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def model_entry_from_mapping(raw: object) -> LocalModelEntry:
    if not isinstance(raw, dict):
        raise ValueError("local_model_catalog_invalid")
    model_id = str(raw.get("id") or "").strip()
    if not _ID_RE.fullmatch(model_id):
        raise ValueError("local_model_catalog_invalid")
    sha = str(raw.get("sha256") or "").strip().lower()
    if sha and not is_sha256_digest(sha):
        raise ValueError("local_model_catalog_invalid")
    download_url = str(raw.get("download_url") or "").strip()
    if download_url:
        download_url = safe_model_url(download_url)
    description = raw.get("description") or ""
    translations = raw.get("description_translations") or {}
    if isinstance(description, dict):
        translations = description
        description = description.get("en_US", "")
    if not isinstance(description, str) or not isinstance(translations, dict):
        raise ValueError("local_model_catalog_invalid")
    return LocalModelEntry(
        id=model_id,
        display_name=str(raw.get("display_name") or model_id).strip() or model_id,
        filename=safe_model_filename(str(raw.get("filename") or "")),
        status=str(raw.get("status") or "stable").strip() or "stable",
        sha256=sha,
        download_url=download_url,
        estimated_size_mb=max(0, _integer_or_default(raw.get("estimated_size_mb"))),
        min_ram_gb=max(0, _integer_or_default(raw.get("min_ram_gb"))),
        context_length=max(1, _integer_or_default(raw.get("context_length"), 8192)),
        max_output_tokens=max(1, _integer_or_default(raw.get("max_output_tokens"), 2048)),
        description=description.strip(),
        description_translations={key: value.strip() for key, value in translations.items()
                                  if isinstance(key, str) and isinstance(value, str)},
        license=str(raw.get("license") or "").strip(),
    )


def _integer_or_default(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def bundled_model_catalog_path() -> Path:
    package = Path(__file__).resolve().parents[2]
    bundled = package / "assets/models/model_catalog.json"
    return bundled if bundled.is_file() else package.parent / "model_catalog.json"


def catalog_entries(items: list[object]) -> list[LocalModelEntry]:
    entries = {}
    for item in items:
        try:
            entry = model_entry_from_mapping(item)
        except (ValueError, TypeError):
            continue
        entries.setdefault(entry.id, entry)
    return list(entries.values())
