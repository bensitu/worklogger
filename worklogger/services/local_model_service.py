"""Local GGUF model catalog, shared availability, and lazy inference.

The remote GitHub file is ``model_catalog.json``. At runtime it is cached as
``models/catalog.json`` and merged with locally preserved/imported GGUF entries.
The GGUF files and ``manifest.json`` are shared globally. The active model id is
stored per user through the settings service.
"""

from __future__ import annotations

import abc
import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Optional

from config.constants import (
    APP_VERSION,
    CATALOG_FILENAME,
    LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
    LOCAL_MODEL_ENABLED_SETTING_KEY,
    MODEL_CATALOG_FETCH_RETRY_ATTEMPTS,
    MODEL_CATALOG_FETCH_RETRY_BACKOFF_SECONDS,
    MODEL_CATALOG_FETCH_TIMEOUT_SECONDS,
    MODEL_CATALOG_LOCAL_PRESERVED_KEY,
    MODEL_CATALOG_REMOTE_URL,
    MODEL_CATALOG_RESPONSE_MAX_BYTES,
)


LOCAL_MODEL_SENTINEL = "__local__"

LOCK_FILENAME = ".download.lock"
MANIFEST_FILENAME = "manifest.json"

SUPPORTED_CATALOG_LOCALES = ("en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR")
REMOTE_PROVIDER = "huggingface"
REMOTE_REPO_TYPE = "model"
MODEL_STATUSES = {"stable", "experimental", "local", "preserved"}

MODEL_FILENAME = "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
MODEL_URL = (
    "https://huggingface.co/bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF"
    "/resolve/main/Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
)

_N_CTX = 8192
_N_THREADS = max(1, (os.cpu_count() or 4) // 2)
_THINKING_RE = re.compile(
    r"(<\|begin_of_thought\|>.*?<\|end_of_thought\|>"
    r"|<think>.*?</think>"
    r"|<thinking>.*?</thinking>)",
    re.DOTALL | re.IGNORECASE,
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def is_local_model_runtime_supported() -> bool:
    """Return False for macOS x86_64 transitional builds."""
    return not (sys.platform == "darwin" and platform.machine() == "x86_64")


def _app_root() -> Path:
    """Return the directory that should contain the runtime models folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    try:
        candidate = Path(sys.argv[0]).resolve().parent
        for _ in range(4):
            if (candidate / "main.py").exists():
                return candidate
            candidate = candidate.parent
    except Exception:
        pass
    return Path(__file__).resolve().parent.parent


def get_models_dir() -> Path:
    """Return the shared runtime ``models/`` directory."""
    return _app_root() / "models"


def validate_model_filename(filename: str) -> str:
    """Return a safe single GGUF filename or raise ``ValueError``."""
    name = str(filename or "").strip()
    win_path = PureWindowsPath(name)
    if (
        not name
        or "/" in name
        or "\\" in name
        or ":" in name
        or any(ord(ch) < 32 for ch in name)
        or name in {".", ".."}
        or ".." in Path(name).parts
        or Path(name).is_absolute()
        or win_path.is_absolute()
        or win_path.drive
        or not (
            name.lower().endswith(".gguf")
            or name.lower().endswith(".gguf.tmp")
        )
    ):
        raise ValueError(f"Unsafe model filename: {filename}")
    return name


def resolve_model_path(models_dir: Path, filename: str) -> Path:
    """Resolve *filename* under *models_dir* and reject traversal attempts."""
    safe_name = validate_model_filename(filename)
    base = Path(models_dir).resolve(strict=False)
    resolved = (base / safe_name).resolve(strict=False)
    try:
        common = os.path.commonpath([
            os.path.normcase(str(base)),
            os.path.normcase(str(resolved)),
        ])
    except ValueError as exc:
        raise ValueError(f"Unsafe model filename: {filename}") from exc
    if common != os.path.normcase(str(base)):
        raise ValueError(f"Unsafe model filename: {filename}")
    return resolved


def validate_model_url(url: str) -> str:
    """Return a safe HTTPS model URL or raise ``ValueError``."""
    candidate = str(url or "")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        raise ValueError(f"URL contains control characters: {url!r}")
    raw = candidate.strip()
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError(f"Unsafe model URL: {url}")
    host = parsed.hostname.strip().lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError(f"Unsafe model URL host: {parsed.hostname}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host) or re.fullmatch(
            r"(0x[0-9a-f]+)(\.(0x[0-9a-f]+))*",
            host,
        ):
            raise ValueError(f"Unsafe model URL host: {parsed.hostname}")
        return raw
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError(f"Unsafe model URL host: {parsed.hostname}")
    return raw


def _is_remote_entry(entry: dict) -> bool:
    return bool(str(entry.get("download_url", "")).strip())


def _require_text(entry: dict, field: str) -> str:
    value = str(entry.get(field, "")).strip()
    if not value:
        raise ValueError("model_catalog_invalid")
    entry[field] = value
    return value


def _require_number(entry: dict, field: str, *, positive: bool) -> None:
    try:
        value = float(entry.get(field))
    except (TypeError, ValueError) as exc:
        raise ValueError("model_catalog_invalid") from exc
    if positive and value <= 0:
        raise ValueError("model_catalog_invalid")
    if not positive and value < 0:
        raise ValueError("model_catalog_invalid")
    entry[field] = int(value) if float(value).is_integer() else value


def _require_int(entry: dict, field: str, *, positive: bool) -> None:
    try:
        value = int(entry.get(field))
    except (TypeError, ValueError) as exc:
        raise ValueError("model_catalog_invalid") from exc
    if positive and value <= 0:
        raise ValueError("model_catalog_invalid")
    if not positive and value < 0:
        raise ValueError("model_catalog_invalid")
    entry[field] = value


def _validate_description(entry: dict, *, remote: bool) -> None:
    value = entry.get("description")
    if isinstance(value, str):
        value = {"en_US": value}
    if not isinstance(value, dict):
        if remote:
            raise ValueError("model_catalog_invalid")
        value = {"en_US": ""}
    normalized: dict[str, str] = {}
    for locale in SUPPORTED_CATALOG_LOCALES:
        raw = value.get(locale)
        if raw is None and not remote:
            raw = value.get("en_US") or next(iter(value.values()), "")
        if not isinstance(raw, str) or (remote and not raw.strip()):
            raise ValueError("model_catalog_invalid")
        normalized[locale] = raw.strip()
    entry["description"] = normalized


def validate_catalog_data(data: Any, *, require_url: bool = True) -> dict:
    """Return a validated catalog object using the new field names."""
    if not isinstance(data, dict):
        raise ValueError("model_catalog_invalid")
    default_model_id = str(data.get("default_model_id", "")).strip()
    models_raw = data.get("models")
    if not default_model_id or not isinstance(models_raw, list) or not models_raw:
        raise ValueError("model_catalog_invalid")

    seen: set[str] = set()
    models: list[dict] = []
    remote_ids: set[str] = set()
    for raw_entry in models_raw:
        if not isinstance(raw_entry, dict):
            raise ValueError("model_catalog_invalid")
        entry = dict(raw_entry)
        entry_id = _require_text(entry, "id")
        if entry_id in seen or not _ID_RE.fullmatch(entry_id):
            raise ValueError("model_catalog_invalid")
        seen.add(entry_id)

        _require_text(entry, "display_name")
        entry["filename"] = validate_model_filename(str(entry.get("filename", "")))
        if not entry["filename"].lower().endswith(".gguf"):
            raise ValueError("model_catalog_invalid")
        status = str(entry.get("status", "")).strip()
        if status not in MODEL_STATUSES:
            raise ValueError("model_catalog_invalid")
        entry["status"] = status

        download_url = str(entry.get("download_url", "")).strip()
        remote = bool(download_url)
        if require_url and status in {"stable", "experimental"}:
            remote = True
        if remote:
            entry["provider"] = _require_text(entry, "provider")
            entry["repo_type"] = _require_text(entry, "repo_type")
            entry["repo_id"] = _require_text(entry, "repo_id")
            entry["revision"] = _require_text(entry, "revision")
            entry["file_format"] = _require_text(entry, "file_format")
            if entry["provider"] != REMOTE_PROVIDER:
                raise ValueError("model_catalog_invalid")
            if entry["repo_type"] != REMOTE_REPO_TYPE:
                raise ValueError("model_catalog_invalid")
            if not re.fullmatch(r"[^/\s]+/[^/\s]+", entry["repo_id"]):
                raise ValueError("model_catalog_invalid")
            if entry["file_format"] != "gguf":
                raise ValueError("model_catalog_invalid")
            entry["download_url"] = validate_model_url(download_url)
            if not entry["download_url"].lower().startswith("https://huggingface.co/"):
                raise ValueError("model_catalog_invalid")
            sha = str(entry.get("sha256", "")).strip().lower()
            if not _SHA_RE.fullmatch(sha):
                raise ValueError("model_catalog_invalid")
            entry["sha256"] = sha
            remote_ids.add(entry_id)
        else:
            if require_url:
                raise ValueError("model_catalog_invalid")
            entry["provider"] = str(entry.get("provider", "")).strip()
            entry["repo_type"] = str(entry.get("repo_type", "")).strip()
            entry["repo_id"] = str(entry.get("repo_id", "")).strip()
            entry["revision"] = str(entry.get("revision", "")).strip()
            entry["file_format"] = str(entry.get("file_format", "gguf")).strip() or "gguf"
            if entry["file_format"] != "gguf":
                raise ValueError("model_catalog_invalid")
            entry["download_url"] = ""
            sha = str(entry.get("sha256", "")).strip().lower()
            if sha and not _SHA_RE.fullmatch(sha):
                raise ValueError("model_catalog_invalid")
            entry["sha256"] = sha

        _require_text(entry, "quantization")
        _require_number(entry, "estimated_size_mb", positive=True)
        _require_number(entry, "min_ram_gb", positive=False)
        _require_int(entry, "context_length", positive=True)
        _require_int(entry, "max_output_tokens", positive=True)
        _require_text(entry, "license")
        _validate_description(entry, remote=remote)
        models.append(entry)

    if require_url and default_model_id not in remote_ids:
        raise ValueError("model_catalog_invalid")
    if not require_url and default_model_id not in seen:
        raise ValueError("model_catalog_invalid")
    return {"default_model_id": default_model_id, "models": models}


def _strip_thinking(text: str) -> str:
    """Remove reasoning blocks before returning text to the UI."""
    cleaned = _THINKING_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def ensure_catalog(models_dir: Optional[Path] = None) -> None:
    """Ensure the shared writable models directory exists."""
    (models_dir or get_models_dir()).mkdir(parents=True, exist_ok=True)


def _built_in_catalog_data() -> dict:
    return {
        "default_model_id": "qwen3_4b_instruct_2507_q4",
        "models": [
            {
                "id": "qwen3_4b_instruct_2507_q4",
                "display_name": "Qwen3-4B-Instruct-2507 Q4_K_M",
                "provider": "huggingface",
                "repo_type": "model",
                "repo_id": "bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF",
                "revision": "main",
                "filename": MODEL_FILENAME,
                "file_format": "gguf",
                "quantization": "Q4_K_M",
                "download_url": MODEL_URL,
                "sha256": "2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e",
                "estimated_size_mb": 2600,
                "min_ram_gb": 6,
                "context_length": 32768,
                "max_output_tokens": 8192,
                "license": "apache-2.0",
                "status": "stable",
                "description": {
                    "en_US": "Qwen3-4B 4-bit - balanced default model for multilingual text generation and polishing.",
                    "zh_CN": "Qwen3-4B 4-bit - 多语言文本生成与润色的默认均衡模型。",
                    "zh_TW": "Qwen3-4B 4-bit - 多語言文本生成與潤飾的預設均衡模型。",
                    "ja_JP": "Qwen3-4B 4-bit - 多言語の文章生成・推敲に適した標準バランスモデルです。",
                    "ko_KR": "Qwen3-4B 4-bit - 다국어 텍스트 생성과 다듬기에 적합한 기본 균형형 모델입니다.",
                },
            }
        ],
    }


def _read_catalog_file(path: Path, *, fallback: bool) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            return validate_catalog_data(json.load(fh), require_url=False)
    if fallback:
        return validate_catalog_data(_built_in_catalog_data(), require_url=True)
    return {"default_model_id": "", "models": []}


def _save_catalog_data(catalog_data: dict, models_dir: Path) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / CATALOG_FILENAME
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(catalog_data, fh, indent=2, ensure_ascii=False)
        shutil.move(str(tmp), str(path))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _model_file_exists(models_dir: Path, filename: str) -> bool:
    try:
        path = resolve_model_path(models_dir, filename)
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except (OSError, ValueError):
        return False


def _manifest_entry_from_catalog(entry: dict, models_dir: Path | None = None) -> dict:
    filename = str(entry.get("filename", "")).strip()
    out = {
        "id": entry.get("id", ""),
        "filename": filename,
        "download_url": entry.get("download_url", ""),
        "repo_id": entry.get("repo_id", ""),
        "revision": entry.get("revision", ""),
        "sha256": str(entry.get("sha256", "")).strip().lower(),
        "available": False,
        "status": entry.get("status", ""),
    }
    if models_dir is not None:
        out["available"] = _model_file_exists(models_dir, filename)
    return out


def _normalize_manifest_entry(entry: dict) -> dict:
    """Normalize shared availability metadata."""
    filename = str(entry.get("filename") or "").strip()
    download_url = str(entry.get("download_url") or "").strip()
    sha = str(entry.get("sha256", "")).strip().lower()
    return {
        "id": str(entry.get("id", "")).strip(),
        "filename": validate_model_filename(filename) if filename else "",
        "download_url": download_url,
        "repo_id": str(entry.get("repo_id") or "").strip(),
        "revision": str(entry.get("revision") or "main").strip(),
        "sha256": sha if _SHA_RE.fullmatch(sha) else "",
        "available": bool(entry.get("available", False)),
        "status": str(entry.get("status", "")).strip(),
        "active": bool(entry.get("active", False)),
    }


def _write_manifest(entries: list[dict], models_dir: Path) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / MANIFEST_FILENAME
    tmp = path.with_suffix(".tmp")
    data = []
    for entry in entries:
        item = dict(entry)
        item.pop("active", None)
        data.append(item)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
        shutil.move(str(tmp), str(path))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def load_catalog_data(models_dir: Optional[Path] = None) -> dict:
    """Load the runtime catalog object."""
    models_dir = models_dir or get_models_dir()
    try:
        return _read_catalog_file(models_dir / CATALOG_FILENAME, fallback=True)
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return validate_catalog_data(_built_in_catalog_data(), require_url=True)


def load_catalog(models_dir: Optional[Path] = None) -> list[dict]:
    """Return catalog model entries only."""
    return list(load_catalog_data(models_dir).get("models", []))


def get_default_model_id(models_dir: Optional[Path] = None) -> str:
    """Return the catalog default model id."""
    return str(load_catalog_data(models_dir).get("default_model_id", "")).strip()


def get_catalog_entry(entry_id: str, models_dir: Optional[Path] = None) -> dict:
    """Return a model entry by id, falling back to the catalog default."""
    catalog_data = load_catalog_data(models_dir)
    models = list(catalog_data.get("models", []))
    wanted = str(entry_id or "").strip()
    for entry in models:
        if entry.get("id") == wanted:
            return entry
    default_id = str(catalog_data.get("default_model_id", "")).strip()
    for entry in models:
        if entry.get("id") == default_id:
            return entry
    return models[0] if models else {}


def localize_field(entry: dict, field: str, lang: str) -> str:
    """Return localized text using en_US and first-value fallback."""
    value = entry.get(field, "")
    if isinstance(value, dict):
        lang_key = str(lang or "")
        if value.get(lang_key):
            return str(value[lang_key])
        if value.get("en_US"):
            return str(value["en_US"])
        first = next((v for v in value.values() if v), "")
        return str(first) if first else ""
    return str(value) if value else ""


def _sync_manifest_with_catalog(manifest: list[dict], models_dir: Path) -> tuple[list[dict], bool]:
    catalog = load_catalog(models_dir)
    by_id = {str(entry.get("id", "")): dict(entry) for entry in manifest}
    changed = False
    ordered: list[dict] = []

    for cat_entry in catalog:
        entry_id = str(cat_entry.get("id", "")).strip()
        if not entry_id:
            continue
        base = _manifest_entry_from_catalog(cat_entry, models_dir)
        existing = by_id.pop(entry_id, None)
        if existing:
            base["sha256"] = existing.get("sha256") or base["sha256"]
            base["available"] = _model_file_exists(models_dir, base["filename"])
            base["status"] = cat_entry.get("status", existing.get("status", ""))
            if existing != base:
                changed = True
        else:
            changed = True
        ordered.append(base)

    for entry_id, existing in by_id.items():
        filename = str(existing.get("filename", "")).strip()
        if filename and _model_file_exists(models_dir, filename):
            existing["available"] = True
            ordered.append(existing)
        else:
            changed = True
    return ordered, changed


def load_manifest(models_dir: Optional[Path] = None) -> list[dict]:
    """Read shared availability metadata and sync it with the current catalog."""
    models_dir = models_dir or get_models_dir()
    ensure_catalog(models_dir)
    path = models_dir / MANIFEST_FILENAME
    raw_entries: list[dict] = []
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, dict):
                        normalized = _normalize_manifest_entry(item)
                        if normalized.get("id") and normalized.get("filename"):
                            raw_entries.append(normalized)
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            raw_entries = []
    manifest, changed = _sync_manifest_with_catalog(raw_entries, models_dir)
    if changed or not path.exists():
        _write_manifest(manifest, models_dir)
    return manifest


def _manifest_entry_by_id(manifest: list[dict], entry_id: str) -> dict:
    for entry in manifest:
        if entry.get("id") == entry_id:
            return entry
    return {}


def _legacy_active_entry_id(manifest: list[dict], models_dir: Optional[Path] = None) -> str:
    for entry in manifest:
        if entry.get("active", False):
            return str(entry.get("id", ""))
    return get_default_model_id(models_dir)


def get_entry(
    manifest: list[dict],
    entry_id: str = "local",
    *,
    services=None,
    user_id: int | None = None,
    models_dir: Optional[Path] = None,
) -> dict:
    """Return a shared manifest entry; ``local`` resolves to one user's active id."""
    models_dir = models_dir or get_models_dir()
    target_id = str(entry_id or "").strip()
    if target_id == "local":
        direct = _manifest_entry_by_id(manifest, "local")
        if direct:
            return direct
        target_id = get_active_entry_id(
            models_dir=models_dir,
            services=services,
            user_id=user_id,
        )
    found = _manifest_entry_by_id(manifest, target_id)
    if found:
        return found
    cat_entry = get_catalog_entry(target_id, models_dir)
    if cat_entry.get("id") == target_id:
        return _manifest_entry_from_catalog(cat_entry, models_dir)
    default_id = get_default_model_id(models_dir)
    return _manifest_entry_by_id(manifest, default_id) or (
        manifest[0] if manifest else {}
    )


def _setting_getter(services, key: str, default: str, user_id: int | None = None) -> str:
    if services is None:
        return default
    if user_id is not None and hasattr(services, "db"):
        return str(services.db.get_setting(key, default, user_id=int(user_id)) or default)
    if hasattr(services, "get_setting"):
        return str(services.get_setting(key, default) or default)
    if hasattr(services, "get_setting"):
        return str(services.get_setting(key, default) or default)
    return default


def _setting_setter(services, key: str, value: str, user_id: int | None = None) -> None:
    if services is None:
        return
    if user_id is not None and hasattr(services, "db"):
        services.db.set_setting(key, value, user_id=int(user_id))
        return
    if hasattr(services, "set_setting"):
        services.set_setting(key, value)


def get_active_model_id_for_user(
    services,
    user_id: int | None = None,
    *,
    models_dir: Optional[Path] = None,
) -> str:
    """Return one user's active model id or the catalog default."""
    default_id = get_default_model_id(models_dir)
    active_id = _setting_getter(
        services,
        LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
        "",
        user_id=user_id,
    ).strip()
    if not active_id:
        return default_id
    catalog_ids = {entry.get("id") for entry in load_catalog(models_dir)}
    manifest_ids = {entry.get("id") for entry in load_manifest(models_dir)}
    return active_id if active_id in catalog_ids or active_id in manifest_ids else default_id


def set_active_model_id_for_user(
    services,
    model_id: str,
    user_id: int | None = None,
    *,
    models_dir: Optional[Path] = None,
) -> None:
    """Store one user's active model id."""
    model_id = str(model_id or "").strip()
    if not model_id:
        clear_active_model_id_for_user(services, user_id)
        return
    catalog_ids = {entry.get("id") for entry in load_catalog(models_dir)}
    manifest_ids = {entry.get("id") for entry in load_manifest(models_dir)}
    if model_id not in catalog_ids and model_id not in manifest_ids:
        raise ValueError(f"Entry id '{model_id}' not found in manifest or catalog.")
    _setting_setter(services, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, model_id, user_id=user_id)


def clear_active_model_id_for_user(services, user_id: int | None = None) -> None:
    """Clear one user's active local model setting."""
    _setting_setter(services, LOCAL_MODEL_ACTIVE_ID_SETTING_KEY, "", user_id=user_id)


def list_users_using_model(services, model_id: str) -> list[int]:
    """Return user ids whose active local model setting references *model_id*."""
    model_id = str(model_id or "").strip()
    if not model_id or services is None or not hasattr(services, "db"):
        return []
    db = services.db
    if hasattr(db, "list_user_ids_by_setting"):
        return [int(x) for x in db.list_user_ids_by_setting(
            LOCAL_MODEL_ACTIVE_ID_SETTING_KEY,
            model_id,
        )]
    return []


def get_active_entry_id(
    models_dir: Optional[Path] = None,
    *,
    services=None,
    user_id: int | None = None,
) -> str:
    """Return the current user's active model id, or the catalog default."""
    models_dir = models_dir or get_models_dir()
    if services is not None or user_id is not None:
        return get_active_model_id_for_user(services, user_id, models_dir=models_dir)
    try:
        return _legacy_active_entry_id(load_manifest(models_dir), models_dir)
    except Exception:
        return get_default_model_id(models_dir)


def set_active_entry(
    entry_id: str,
    models_dir: Optional[Path] = None,
    *,
    services=None,
    user_id: int | None = None,
) -> None:
    """Set the active model for one user; legacy callers update manifest only."""
    models_dir = models_dir or get_models_dir()
    if services is not None or user_id is not None:
        set_active_model_id_for_user(services, entry_id, user_id, models_dir=models_dir)
        return

    manifest = load_manifest(models_dir)
    found = False
    for entry in manifest:
        entry["active"] = entry.get("id") == entry_id
        found = found or bool(entry["active"])
    if not found:
        cat_entry = get_catalog_entry(entry_id, models_dir)
        if cat_entry.get("id") != entry_id:
            raise ValueError(f"Entry id '{entry_id}' not found in manifest or catalog.")
        new_entry = _manifest_entry_from_catalog(cat_entry, models_dir)
        new_entry["active"] = True
        manifest.append(new_entry)
    path = models_dir / MANIFEST_FILENAME
    tmp = path.with_suffix(".tmp")
    models_dir.mkdir(parents=True, exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)
    shutil.move(str(tmp), str(path))


def update_sha256_in_manifest(
    sha256: str,
    models_dir: Path,
    entry_id: str = "local",
    *,
    services=None,
    user_id: int | None = None,
) -> None:
    """Persist SHA-256 and availability for one shared model entry."""
    manifest = load_manifest(models_dir)
    target_id = entry_id
    if target_id == "local":
        target_id = get_active_entry_id(
            models_dir=models_dir,
            services=services,
            user_id=user_id,
        )
    changed = False
    for entry in manifest:
        if entry.get("id") == target_id:
            entry["sha256"] = str(sha256 or "").strip().lower()
            entry["available"] = _model_file_exists(models_dir, entry.get("filename", ""))
            changed = True
    if changed:
        _write_manifest(manifest, models_dir)


def is_model_available(model_id: str, models_dir: Optional[Path] = None) -> bool:
    """Return True when the shared GGUF exists and passes integrity rules."""
    models_dir = models_dir or get_models_dir()
    return verify_model_file(models_dir, model_id)


def delete_model_file(
    entry_id: str,
    models_dir: Optional[Path] = None,
    *,
    services=None,
    user_id: int | None = None,
) -> None:
    """Delete a shared GGUF file and clear its shared availability metadata."""
    models_dir = models_dir or get_models_dir()
    manifest = load_manifest(models_dir)
    entry = get_entry(
        manifest,
        entry_id,
        services=services,
        user_id=user_id,
        models_dir=models_dir,
    )
    path = resolve_model_path(models_dir, entry.get("filename", ""))
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    update_sha256_in_manifest("", models_dir, str(entry.get("id", entry_id)))
    _prune_missing_local_catalog_entries(models_dir)


def delete_model_if_unused(
    model_id: str,
    current_user_id: int,
    services,
    models_dir: Optional[Path] = None,
) -> bool:
    """Delete a shared model only when no other user references it."""
    users = set(list_users_using_model(services, model_id))
    others = {uid for uid in users if uid != int(current_user_id)}
    if others:
        return False
    if int(current_user_id) in users:
        clear_active_model_id_for_user(services, int(current_user_id))
    delete_model_file(model_id, models_dir, services=services, user_id=current_user_id)
    return True


def _prune_missing_local_catalog_entries(models_dir: Path) -> None:
    catalog_data = load_catalog_data(models_dir)
    remote = []
    local = []
    changed = False
    for entry in catalog_data.get("models", []):
        status = entry.get("status")
        if status not in {"local", "preserved"}:
            remote.append(entry)
            continue
        if _model_file_exists(models_dir, str(entry.get("filename", ""))):
            local.append(entry)
        else:
            changed = True
    if changed:
        _save_catalog_data(
            {
                "default_model_id": catalog_data.get("default_model_id", ""),
                "models": remote + local,
            },
            models_dir,
        )


def _entry_has_shared_file(entry: dict, manifest: list[dict], models_dir: Path) -> bool:
    filename = str(entry.get("filename", "")).strip()
    if filename and _model_file_exists(models_dir, filename):
        return True
    manifest_entry = _manifest_entry_by_id(manifest, str(entry.get("id", "")))
    filename = str(manifest_entry.get("filename", "")).strip()
    return bool(filename and _model_file_exists(models_dir, filename))


def refresh_catalog_from_remote(
    models_dir: Optional[Path] = None,
    *,
    url: str = MODEL_CATALOG_REMOTE_URL,
    ssl_context: Any = None,
) -> list[dict]:
    """Fetch the GitHub catalog, merge local entries, and cache it locally."""
    models_dir = models_dir or get_models_dir()
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"WorkLogger/{APP_VERSION}",
            "Accept": "application/json",
        },
    )
    raw = b""
    for attempt in range(max(1, MODEL_CATALOG_FETCH_RETRY_ATTEMPTS)):
        try:
            with urllib.request.urlopen(
                request,
                timeout=MODEL_CATALOG_FETCH_TIMEOUT_SECONDS,
                context=ssl_context,
            ) as response:
                raw = response.read(MODEL_CATALOG_RESPONSE_MAX_BYTES + 1)
            break
        except urllib.error.URLError:
            if attempt + 1 >= max(1, MODEL_CATALOG_FETCH_RETRY_ATTEMPTS):
                raise
            time.sleep(MODEL_CATALOG_FETCH_RETRY_BACKOFF_SECONDS * (attempt + 1))
    if len(raw) > MODEL_CATALOG_RESPONSE_MAX_BYTES:
        raise ValueError("model_catalog_too_large")
    try:
        remote_catalog = validate_catalog_data(
            json.loads(raw.decode("utf-8")),
            require_url=True,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("model_catalog_invalid") from exc

    try:
        old_catalog = _read_catalog_file(models_dir / CATALOG_FILENAME, fallback=False)
    except Exception:
        old_catalog = {"default_model_id": "", "models": []}
    try:
        manifest = load_manifest(models_dir)
    except Exception:
        manifest = []

    remote_ids = {entry["id"] for entry in remote_catalog["models"]}
    preserved: list[dict] = []
    for entry in old_catalog.get("models", []):
        entry_id = str(entry.get("id", "")).strip()
        if not entry_id or entry_id in remote_ids:
            continue
        if entry.get("status") == "local" or _entry_has_shared_file(entry, manifest, models_dir):
            preserved_entry = dict(entry)
            if preserved_entry.get("status") != "local":
                preserved_entry["status"] = "preserved"
                preserved_entry[MODEL_CATALOG_LOCAL_PRESERVED_KEY] = True
            preserved.append(preserved_entry)

    merged = {
        "default_model_id": remote_catalog["default_model_id"],
        "models": remote_catalog["models"] + preserved,
    }
    _save_catalog_data(merged, models_dir)
    manifest, _changed = _sync_manifest_with_catalog(manifest, models_dir)
    _write_manifest(manifest, models_dir)
    return list(merged["models"])


def _sha256_of_file_detailed(
    path: Path,
    *,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout_s: Optional[float] = None,
) -> tuple[str, str]:
    if not path:
        return "", "missing"
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return "", "missing"
        total = max(0, int(p.stat().st_size))
    except (OSError, ValueError):
        return "", "missing"

    h = hashlib.sha256()
    start_ts = time.monotonic()
    processed = 0
    try:
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                if cancel_event is not None and cancel_event.is_set():
                    return "", "cancelled"
                if timeout_s is not None and timeout_s > 0:
                    if (time.monotonic() - start_ts) > timeout_s:
                        return "", "timeout"
                h.update(chunk)
                processed += len(chunk)
                if progress_cb is not None and total > 0:
                    progress_cb(min(99, int((processed * 100) / total)))
    except PermissionError:
        return "", "permission_denied"
    except OSError:
        return "", "io_error"
    if progress_cb is not None:
        progress_cb(100)
    return h.hexdigest().lower(), "ok"


def sha256_of_file(path: Path) -> str:
    """Return the lower-case SHA-256 for *path*, or empty on I/O errors."""
    digest, status = _sha256_of_file_detailed(path)
    return digest if status == "ok" else ""


def verify_model_file_with_reason(
    models_dir: Optional[Path] = None,
    entry_id: str = "local",
    *,
    timeout_s: Optional[float] = None,
    retries: int = 0,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    services=None,
    user_id: int | None = None,
) -> tuple[bool, str]:
    """Verify shared model presence/hash and return ``(ok, reason)``."""
    models_dir = models_dir or get_models_dir()
    try:
        manifest = load_manifest(models_dir)
        entry = get_entry(
            manifest,
            entry_id,
            services=services,
            user_id=user_id,
            models_dir=models_dir,
        )
        filename = str(entry.get("filename", "")).strip()
        if not filename:
            return False, "missing"
        path = resolve_model_path(models_dir, filename)
        if not path.exists():
            return False, "missing"
        if path.stat().st_size == 0:
            return False, "empty"
        expected = str(entry.get("sha256", "")).strip().lower()
        if not expected:
            if progress_cb is not None:
                progress_cb(100)
            return True, "unverified"
    except Exception:
        return False, "manifest_error"

    attempts = max(1, int(retries) + 1)
    last_reason = "io_error"
    for _ in range(attempts):
        digest, status = _sha256_of_file_detailed(
            path,
            progress_cb=progress_cb,
            cancel_event=cancel_event,
            timeout_s=timeout_s,
        )
        if status == "ok":
            if digest == expected:
                return True, "ok"
            return False, "hash_mismatch"
        if status in {"timeout", "io_error"}:
            last_reason = status
            continue
        return False, status
    return False, last_reason


def verify_model_file(
    models_dir: Optional[Path] = None,
    entry_id: str = "local",
    *,
    timeout_s: Optional[float] = None,
    retries: int = 0,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    services=None,
    user_id: int | None = None,
) -> bool:
    ok, _reason = verify_model_file_with_reason(
        models_dir=models_dir,
        entry_id=entry_id,
        timeout_s=timeout_s,
        retries=retries,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
        services=services,
        user_id=user_id,
    )
    return ok


def _safe_custom_id(stem: str, sha: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_").lower() or "model"
    return f"custom_{base}_{sha[:8]}"


def _all_locale_description(text: str) -> dict[str, str]:
    return {locale: text for locale in SUPPORTED_CATALOG_LOCALES}


def _unique_destination(models_dir: Path, src_filename: str, src_sha: str) -> Path:
    safe_name = validate_model_filename(src_filename)
    dest = resolve_model_path(models_dir, safe_name)
    if not dest.exists():
        return dest
    if sha256_of_file(dest) == src_sha:
        return dest
    stem = Path(safe_name).stem
    return resolve_model_path(models_dir, f"{stem}-{src_sha[:8]}.gguf")


def _uses_qwen3_non_thinking(model_id: str, entry: dict) -> bool:
    source = " ".join(
        str(entry.get(key, ""))
        for key in ("id", "display_name", "repo_id", "filename")
    ).lower()
    return ("qwen3" in source or "qwen35" in str(model_id).lower()) and "qwen2.5" not in source


def _messages_with_no_think(messages: list[dict], model_id: str, entry: dict) -> list[dict]:
    copied = [dict(msg) for msg in messages if isinstance(msg, dict)]
    if not _uses_qwen3_non_thinking(model_id, entry):
        return copied
    for msg in copied:
        if msg.get("role") == "system":
            content = str(msg.get("content", "")).strip()
            if "/no_think" not in content:
                msg["content"] = (content + "\n\n/no_think").strip()
            return copied
    return [{"role": "system", "content": "/no_think"}, *copied]


class LLMProvider(abc.ABC):
    """Minimal interface for local inference backends."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Return True when loaded and ready."""

    @abc.abstractmethod
    def load(self) -> None:
        """Initialize the provider."""

    @abc.abstractmethod
    def unload(self) -> None:
        """Release provider resources."""

    @abc.abstractmethod
    def generate(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """Run inference and return assistant text."""


class LlamaCppProvider(LLMProvider):
    """llama-cpp-python backend, loaded only when inference is requested."""

    def __init__(
        self,
        model_path: Path,
        *,
        model_id: str,
        catalog_entry: dict,
        n_ctx: int = _N_CTX,
        n_threads: int = _N_THREADS,
        n_gpu_layers: int = 0,
    ) -> None:
        self._model_path = Path(model_path) if model_path else Path()
        self._model_id = str(model_id or "")
        self._catalog_entry = dict(catalog_entry or {})
        self._n_ctx = max(512, int(n_ctx))
        self._n_threads = max(1, int(n_threads))
        self._n_gpu_layers = max(0, int(n_gpu_layers))
        self._llama: Any = None
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        with self._lock:
            return self._llama is not None

    def load(self) -> None:
        with self._lock:
            if self._llama is not None:
                return
            if not is_local_model_runtime_supported():
                raise RuntimeError("ai_assist.local_model_not_running")
            from services.dep_installer import ensure_inference_deps

            ensure_inference_deps()
            try:
                from llama_cpp import Llama  # type: ignore[import]
            except ImportError as exc:
                raise ImportError(
                    "llama-cpp-python could not be loaded after auto-install. "
                    "Please install it manually: pip install llama-cpp-python"
                ) from exc
            if not self._model_path.exists():
                raise FileNotFoundError(f"Model file not found: {self._model_path}")
            try:
                self._llama = Llama(
                    model_path=str(self._model_path),
                    n_ctx=self._n_ctx,
                    n_threads=self._n_threads,
                    n_gpu_layers=self._n_gpu_layers,
                    verbose=os.environ.get("WORKLOGGER_LLAMA_VERBOSE", "0") == "1",
                )
            except MemoryError:
                raise
            except Exception as exc:
                raise RuntimeError(f"Model load failed: {exc}") from exc

    def unload(self) -> None:
        with self._lock:
            self._llama = None

    def _generate_chat_completion(
        self,
        messages: list[dict],
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        kwargs: dict[str, Any] = {
            "messages": messages,
            "max_tokens": max(1, int(max_tokens)),
            "temperature": float(temperature),
            "top_p": 0.8,
            "top_k": 20,
            "min_p": 0.0,
        }
        try:
            result = self._llama.create_chat_completion(**kwargs)
        except TypeError:
            kwargs.pop("min_p", None)
            result = self._llama.create_chat_completion(**kwargs)
        choices = result.get("choices", [])
        if not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            return "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
            )
        return str(content or "")

    @staticmethod
    def _prompt_from_messages(messages: list[dict]) -> str:
        parts = []
        for msg in messages:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        return "\n".join(parts)

    def generate(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """Run chat completion when available and strip thinking tags."""
        with self._lock:
            if self._llama is None:
                raise RuntimeError("Provider not loaded - call load() first.")
            if not isinstance(messages, (list, tuple)) or not messages:
                raise ValueError("messages must be a non-empty list.")
            prepared = _messages_with_no_think(
                list(messages),
                self._model_id,
                self._catalog_entry,
            )
            try:
                if hasattr(self._llama, "create_chat_completion"):
                    raw = self._generate_chat_completion(
                        prepared,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                else:
                    result = self._llama(
                        self._prompt_from_messages(prepared),
                        max_tokens=max(1, int(max_tokens)),
                        temperature=float(temperature),
                        top_p=0.8,
                        top_k=20,
                        stop=["<|im_end|>", "<|im_start|>"],
                        echo=False,
                    )
                    raw = result["choices"][0]["text"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected llama output format: {exc}") from exc
            return _strip_thinking(raw)


class LocalModelService:
    """Process singleton for shared model files and lazy provider loading."""

    _instance: Optional["LocalModelService"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, models_dir: Optional[Path] = None) -> None:
        self._models_dir = models_dir or get_models_dir()
        self._provider: Optional[LLMProvider] = None
        self._provider_model_id = ""
        self._load_lock = threading.Lock()

    @classmethod
    def get(cls, _services=None) -> "LocalModelService":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._singleton_lock:
            if cls._instance and cls._instance._provider:
                try:
                    cls._instance._provider.unload()
                except Exception:
                    pass
            cls._instance = None

    def is_model_present(self, services=None, user_id: int | None = None) -> bool:
        """Return True when the current user's active shared GGUF exists."""
        try:
            manifest = load_manifest(self._models_dir)
            entry = get_entry(
                manifest,
                "local",
                services=services,
                user_id=user_id,
                models_dir=self._models_dir,
            )
            return _model_file_exists(self._models_dir, entry.get("filename", ""))
        except Exception:
            return False

    def load_provider(self, services=None) -> LLMProvider:
        """Load llama-cpp-python only when inference is requested."""
        with self._load_lock:
            if not is_local_model_runtime_supported():
                raise RuntimeError("ai_assist.local_model_not_running")
            if services is not None and not is_local_model_enabled(services):
                raise RuntimeError("ai_assist.local_model_not_running")
            active_id = get_active_entry_id(
                models_dir=self._models_dir,
                services=services,
            )
            if (
                self._provider
                and self._provider.is_available()
                and self._provider_model_id == active_id
            ):
                return self._provider
            if self._provider:
                self._provider.unload()
                self._provider = None
                self._provider_model_id = ""

            manifest = load_manifest(self._models_dir)
            entry = get_entry(
                manifest,
                active_id,
                services=services,
                models_dir=self._models_dir,
            )
            path = resolve_model_path(self._models_dir, entry.get("filename", MODEL_FILENAME))
            if not path.exists():
                raise FileNotFoundError(
                    f"Model file not found: {path}\n"
                    "Please download it in Settings -> AI."
                )
            cat_entry = get_catalog_entry(active_id, self._models_dir)
            n_ctx = int(cat_entry.get("context_length", _N_CTX))
            provider = LlamaCppProvider(
                path,
                model_id=active_id,
                catalog_entry=cat_entry,
                n_ctx=n_ctx,
            )
            provider.load()
            self._provider = provider
            self._provider_model_id = active_id
            return provider

    def unload_provider(self) -> None:
        with self._load_lock:
            if self._provider:
                self._provider.unload()
                self._provider = None
                self._provider_model_id = ""

    def generate(
        self,
        messages: list,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        services=None,
    ) -> str:
        if not messages:
            raise ValueError("messages must not be empty.")
        provider = self.load_provider(services=services)
        return provider.generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def import_gguf(self, source_path: str, entry_id: str = "local", *, services=None) -> Path:
        """Copy or reuse a user-supplied GGUF in the shared models directory."""
        src_p = Path(source_path)
        if not src_p.exists():
            raise FileNotFoundError(f"File not found: {source_path}")
        if src_p.stat().st_size == 0:
            raise ValueError(f"File is empty: {source_path}")
        if src_p.suffix.lower() != ".gguf":
            raise ValueError(f"Unsupported model file: {source_path}")
        self._models_dir.mkdir(parents=True, exist_ok=True)

        src_sha = sha256_of_file(src_p)
        catalog_data = load_catalog_data(self._models_dir)
        catalog = list(catalog_data.get("models", []))
        src_filename = validate_model_filename(src_p.name)

        matched = next(
            (
                entry for entry in catalog
                if str(entry.get("filename", "")).lower() == src_filename.lower()
                or (src_sha and str(entry.get("sha256", "")).lower() == src_sha)
            ),
            None,
        )
        if matched is not None and str(matched.get("filename", "")).strip():
            dest = _unique_destination(self._models_dir, str(matched["filename"]), src_sha)
            target_id = str(matched["id"])
        else:
            dest = _unique_destination(self._models_dir, src_filename, src_sha)
            target_id = _safe_custom_id(dest.stem, src_sha)
            display_name = src_p.stem
            new_cat_entry = {
                "id": target_id,
                "display_name": display_name,
                "provider": "",
                "repo_type": "",
                "repo_id": "",
                "revision": "",
                "filename": dest.name,
                "file_format": "gguf",
                "quantization": "custom",
                "download_url": "",
                "sha256": src_sha,
                "estimated_size_mb": max(1, int(src_p.stat().st_size / 1_048_576)),
                "min_ram_gb": 0,
                "context_length": 8192,
                "max_output_tokens": 2048,
                "license": "custom",
                "status": "local",
                "description": _all_locale_description(f"Local model: {dest.name}"),
            }
            catalog.append(new_cat_entry)
            catalog_data["models"] = catalog
            _save_catalog_data(catalog_data, self._models_dir)

        if not dest.exists() or sha256_of_file(dest) != src_sha:
            shutil.copy2(str(src_p), str(dest))

        manifest = load_manifest(self._models_dir)
        if not _manifest_entry_by_id(manifest, target_id):
            cat_entry = get_catalog_entry(target_id, self._models_dir)
            manifest.append(_manifest_entry_from_catalog(cat_entry, self._models_dir))
            _write_manifest(manifest, self._models_dir)
        update_sha256_in_manifest(src_sha, self._models_dir, target_id)
        if services is not None:
            set_active_model_id_for_user(services, target_id, models_dir=self._models_dir)
        else:
            set_active_entry(target_id, self._models_dir)
        return dest

    def delete_model(self, entry_id: str = "local", *, services=None) -> None:
        """Unload provider and delete an unused shared GGUF file."""
        self.unload_provider()
        delete_model_file(entry_id, self._models_dir, services=services)


def should_use_local_model(services) -> bool:
    """Return True when local model is enabled and the user's active file is ready."""
    if services is None:
        return False
    try:
        if not is_local_model_enabled(services):
            return False
        active_id = get_active_entry_id(services=services)
        return verify_model_file(entry_id=active_id, services=services)
    except Exception:
        return False


def is_local_model_enabled(services) -> bool:
    """Return True when the current user's local-model switch is enabled."""
    if services is None:
        return False
    if not is_local_model_runtime_supported():
        return False
    try:
        return str(services.get_setting(LOCAL_MODEL_ENABLED_SETTING_KEY, "0")) == "1"
    except Exception:
        return False
