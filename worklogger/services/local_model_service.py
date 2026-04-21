"""Local model service — catalog-driven, JSON-configured, lazy-loading.

Architecture
------------
- **catalog.json** (``<app_root>/models/catalog.json``) is the sole source of
  model metadata.  Add / modify entries there; no Python changes required.
- **manifest.json** records download state (active entry, sha256 per file).
- **LLMProvider** is an ABC; ``LlamaCppProvider`` is the default backend.
  Future backends (Ollama, ONNX) subclass it without touching callers.
- **LocalModelService** is a process singleton with *lazy* provider loading:
  the Llama instance is NOT created at startup — only when inference is first
  requested.  This keeps startup time near-zero.
- **Thinking-tag stripping**: models like SmallThinker / Qwen3 emit
  ``<think>…</think>`` blocks.  ``_strip_thinking()`` removes them so only
  the final answer is returned to the UI.
"""

from __future__ import annotations

import abc
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

# Public sentinel.

LOCAL_MODEL_SENTINEL: str = "__local__"

# Path helpers.

LOCK_FILENAME:     str = ".download.lock"
MANIFEST_FILENAME: str = "manifest.json"
CATALOG_FILENAME:  str = "catalog.json"

# llama-cpp-python load parameters
# SmallThinker-3B and Qwen2.5-3B are trained with 32768-token context.
# Use 8192 as a practical default (fits comfortably in RAM on typical hardware).
# The catalog.json "n_ctx" field can override this per model.
_N_CTX:     int = 8192
_N_THREADS: int = max(1, (os.cpu_count() or 4) // 2)

# Strip any reasoning/thinking block that models emit before their final answer.
# Covers:
#   <think>…</think>                — Qwen3, DeepSeek-R1
#   <thinking>…</thinking>          — variations
#   <|begin_of_thought|>…<|end_of_thought|>  — SmallThinker
#   \n\n (normalise trailing whitespace)
_THINKING_RE = re.compile(
    r"(<\|begin_of_thought\|>.*?<\|end_of_thought\|>"
    r"|<think>.*?</think>"
    r"|<thinking>.*?</thinking>)",
    re.DOTALL | re.IGNORECASE,
)


def _app_root() -> Path:
    """Return the directory that should be the sibling of models/ and templates/.

    Resolution order (highest priority first):
    1. PyInstaller frozen bundle: sys._MEIPASS parent (the folder that
       contains the .exe/.app), so models/ lands next to the executable —
       NOT inside the temp extraction directory.
    2. Source / dev run: walk up from sys.argv[0] to find main.py.
    3. Last-resort: two levels above this file.
    """
    # 1. Frozen (PyInstaller) — use the executable's own directory, not _MEIPASS.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # 2. Development — find directory containing main.py.
    try:
        candidate = Path(sys.argv[0]).resolve().parent
        for _ in range(4):
            if (candidate / "main.py").exists():
                return candidate
            candidate = candidate.parent
    except Exception:
        pass
    # 3. Fallback.
    return Path(__file__).resolve().parent.parent


def get_models_dir() -> Path:
    """Return ``<app_root>/models/`` — always sibling of ``templates/``."""
    return _app_root() / "models"


# Thinking-tag stripper.

def _strip_thinking(text: str) -> str:
    """Remove ``<think>…</think>`` / ``<thinking>…</thinking>`` blocks.

    After removal, leading/trailing whitespace and blank lines are normalised
    so the result is clean for display in the UI.
    """
    cleaned = _THINKING_RE.sub("", text)
    # Collapse multiple consecutive blank lines into one.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


# Catalog loader.

def _bundled_catalog_path() -> Optional[Path]:
    """Return the path to catalog.json inside the PyInstaller bundle, or None."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / "models" / CATALOG_FILENAME
        if candidate.exists():
            return candidate
    return None


def ensure_catalog(models_dir: Optional[Path] = None) -> None:
    """Guarantee that catalog.json exists in the user's models directory.

    On a frozen (PyInstaller) first run the file only exists inside
    ``sys._MEIPASS`` (the temp extraction folder).  This function copies it
    to ``models_dir`` so it persists between launches and can be edited by
    the user.

    On source / dev runs the file is already in ``worklogger/models/`` and
    nothing happens.

    Always safe to call multiple times (idempotent).
    """
    if models_dir is None:
        models_dir = get_models_dir()
    dest = models_dir / CATALOG_FILENAME
    if dest.exists():
        return
    # Try to copy from the bundle.
    bundled = _bundled_catalog_path()
    if bundled is not None:
        try:
            models_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(bundled), str(dest))
            return
        except OSError:
            pass
    # Source run: catalog lives next to this file's package root.
    # (worklogger/models/catalog.json relative to _app_root())
    candidate = _app_root() / "models" / CATALOG_FILENAME
    if candidate.exists() and candidate != dest:
        try:
            models_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(candidate), str(dest))
        except OSError:
            pass
    # If still not present, load_catalog() will use the hardcoded fallback.


def load_catalog(models_dir: Optional[Path] = None) -> list:
    """Load catalog.json; fall back to a minimal built-in default if absent.

    The catalog is **user-editable**: adding a new entry with a valid HuggingFace
    URL is all that is needed to make a new model available in the UI.

    Generic i18n fallback
    ~~~~~~~~~~~~~~~~~~~~~
    Entries that omit language keys for ``desc`` / ``pros`` fall back to the
    ``"en_US"`` value (or the raw string if that is also absent).  This means
    user-added models without translations still render gracefully.
    """
    if models_dir is None:
        models_dir = get_models_dir()
    path = models_dir / CATALOG_FILENAME
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and data:
                # Filter out malformed entries missing required keys
                valid = [
                    e for e in data
                    if isinstance(e, dict)
                    and e.get("id")
                    and e.get("file")
                    and e.get("url")
                ]
                if valid:
                    return valid
        except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError):
            pass
    # Built-in minimal fallback (one model) so the app works even if
    # catalog.json is missing from the installation.
    return [
        {
            "id":      "q4_k_m",
            "label":   "Balanced",
            "file":    "SmallThinker-3B-Preview-Q4_K_M.gguf",
            "url":     (
                "https://huggingface.co/bartowski/SmallThinker-3B-Preview-GGUF"
                "/resolve/main/SmallThinker-3B-Preview-Q4_K_M.gguf"
            ),
            "sha256":  "",
            "size_mb": 1850,
            "ram_gb":  3,
            "default": True,
            "desc":    {"en_US": "4-bit quantized — balanced speed and quality."},
            "pros":    {"en_US": "✓ Recommended for most users"},
        }
    ]


def get_catalog_entry(entry_id: str,
                      models_dir: Optional[Path] = None) -> dict:
    """Return catalog entry by id; fall back to the default entry."""
    catalog = load_catalog(models_dir)
    for e in catalog:
        if e.get("id") == entry_id:
            return e
    for e in catalog:
        if e.get("default"):
            return e
    return catalog[0] if catalog else {}


def localize_field(entry: dict, field: str, lang: str) -> str:
    """Extract a localised string from a catalog entry's dict field.

    Resolution order: ``entry[field][lang]`` → ``entry[field]["en_US"]``
    → first available value → ``entry[field]`` (if str) → ``""``.

    This provides the generic i18n fallback required by spec §4.
    """
    value = entry.get(field, "")
    if isinstance(value, dict):
        lang_key = str(lang or "")
        order_map = {
            "en_US": ("en_US",),
            "ja_JP": ("ja_JP",),
            "ko_KR": ("ko_KR",),
            "zh_CN": ("zh_CN",),
            "zh_TW": ("zh_TW",),
        }
        for key in order_map.get(lang_key, (lang_key,)):
            val = value.get(key)
            if val:
                return str(val)
        fallback = value.get("en_US") or next(iter(value.values()), "")
        return str(fallback) if fallback else ""
    return str(value) if value else ""


# Derived convenience constants for code that still references them.
def _default_entry() -> dict:
    catalog = load_catalog()
    for e in catalog:
        if e.get("default"):
            return e
    return load_catalog()[0]


MODEL_FILENAME: str = _default_entry().get("file", "model.gguf")
MODEL_URL:      str = _default_entry().get("url",  "")


# Manifest helpers.

def _save_catalog(catalog: list, models_dir: Path) -> None:
    """Persist an updated catalog to catalog.json (atomic write)."""
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / CATALOG_FILENAME
    tmp  = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(catalog, fh, indent=2, ensure_ascii=False)
        shutil.move(str(tmp), str(path))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _write_manifest(entries: list, models_dir: Path) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / MANIFEST_FILENAME
    tmp  = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)
        shutil.move(str(tmp), str(path))
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _build_default_manifest(models_dir: Optional[Path] = None) -> list:
    catalog = load_catalog(models_dir)
    return [
        {
            "id":     e["id"],
            "file":   e.get("file", ""),
            "url":    e.get("url",  ""),
            "sha256": "",
            "active": bool(e.get("default", False)),
        }
        for e in catalog
    ]


def _sync_manifest_with_catalog(manifest: list,
                                 models_dir: Path) -> tuple:
    """Add catalog entries missing from *manifest* and return (updated, changed).

    When a new model is added to catalog.json after the user already has a
    manifest.json on disk, this function adds the new entries so that
    ``set_active_entry()`` never raises ``ValueError`` for a valid catalog id.

    Returns ``(manifest, was_changed)`` so callers can decide whether to
    persist the updated manifest.
    """
    catalog  = load_catalog(models_dir)
    cat_ids  = {e.get("id") for e in catalog}
    man_ids  = {e.get("id") for e in manifest}
    missing  = cat_ids - man_ids
    if not missing:
        return manifest, False
    for cat_entry in catalog:
        if cat_entry.get("id") in missing:
            manifest.append({
                "id":     cat_entry["id"],
                "file":   cat_entry.get("file", ""),
                "url":    cat_entry.get("url",  ""),
                "sha256": "",
                "active": False,
            })
    return manifest, True


def load_manifest(models_dir: Optional[Path] = None) -> list:
    """Read manifest.json; create from catalog defaults if absent or corrupt.

    Also syncs any catalog entries that are missing from an existing manifest
    (e.g. after a software update that adds new models).  The updated manifest
    is written back to disk atomically so the sync is persistent.
    """
    if models_dir is None:
        models_dir = get_models_dir()
    # Guarantee catalog.json exists in models_dir before reading manifest.
    ensure_catalog(models_dir)
    path = models_dir / MANIFEST_FILENAME
    if path.exists():
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list) and data:
                # Sync: add any new catalog entries not yet in manifest.
                synced, changed = _sync_manifest_with_catalog(data, models_dir)
                if changed:
                    try:
                        _write_manifest(synced, models_dir)
                    except OSError:
                        pass
                return synced
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    default = _build_default_manifest(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    _write_manifest(default, models_dir)
    return default


def get_entry(manifest: list, entry_id: str = "local") -> dict:
    """Return manifest entry by id.

    ``"local"`` resolves to the currently active entry.
    If the requested id is not found, return the active entry as fallback.
    """
    if entry_id == "local":
        for e in manifest:
            if e.get("active", False):
                return e
        return manifest[0] if manifest else {}
    for e in manifest:
        if e.get("id") == entry_id:
            return e
    # Fallback to active entry
    return get_entry(manifest, "local")


def get_active_entry_id(models_dir: Optional[Path] = None) -> str:
    manifest = load_manifest(models_dir)
    return get_entry(manifest, "local").get("id", "")


def set_active_entry(entry_id: str,
                     models_dir: Optional[Path] = None) -> None:
    """Mark *entry_id* as active in manifest.json.

    If the id is absent from the manifest but present in catalog.json, it is
    added automatically (handles software-update scenario where new models
    are added to the catalog after the user's manifest was created).

    Raises ``ValueError`` only if the id is not in the catalog either.
    """
    if models_dir is None:
        models_dir = get_models_dir()
    manifest = load_manifest(models_dir)
    found = False
    for e in manifest:
        e["active"] = (e.get("id") == entry_id)
        if e["active"]:
            found = True
    if not found:
        # Last resort: check catalog and add the entry on the fly.
        cat_entry = get_catalog_entry(entry_id, models_dir)
        if cat_entry.get("id") == entry_id:
            manifest.append({
                "id":     entry_id,
                "file":   cat_entry.get("file", ""),
                "url":    cat_entry.get("url",  ""),
                "sha256": "",
                "active": True,
            })
            # Deactivate all others
            for e in manifest[:-1]:
                e["active"] = False
            found = True
        else:
            raise ValueError(
                f"Entry id '{entry_id}' not found in manifest or catalog.")
    _write_manifest(manifest, models_dir)


def update_sha256_in_manifest(sha256: str,
                               models_dir: Path,
                               entry_id: str = "local") -> None:
    """Persist sha256 for *entry_id*.  ``"local"`` resolves to active entry."""
    manifest = load_manifest(models_dir)
    if entry_id == "local":
        target_id = get_entry(manifest, "local").get("id", "")
    else:
        target_id = entry_id
    for e in manifest:
        if e.get("id") == target_id:
            e["sha256"] = sha256
    _write_manifest(manifest, models_dir)


def delete_model_file(entry_id: str,
                      models_dir: Optional[Path] = None) -> None:
    """Delete the GGUF file and clear sha256 in manifest."""
    if models_dir is None:
        models_dir = get_models_dir()
    manifest = load_manifest(models_dir)
    entry    = get_entry(manifest, entry_id)
    path     = models_dir / entry.get("file", "")
    if path and path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    update_sha256_in_manifest("", models_dir, entry_id)


# SHA-256 utilities.

def _sha256_of_file_detailed(
    path: Path,
    *,
    progress_cb: Optional[Callable[[int], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    timeout_s: Optional[float] = None,
) -> tuple[str, str]:
    """Return ``(digest, status)`` while supporting timeout/cancel/progress.

    Status values:
    - ``"ok"``
    - ``"missing"``
    - ``"permission_denied"``
    - ``"io_error"``
    - ``"timeout"``
    - ``"cancelled"``
    """
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
                    try:
                        progress_cb(min(99, int((processed * 100) / total)))
                    except Exception:
                        pass
    except PermissionError:
        return "", "permission_denied"
    except OSError:
        return "", "io_error"

    if progress_cb is not None:
        try:
            progress_cb(100)
        except Exception:
            pass
    return h.hexdigest().lower(), "ok"


def sha256_of_file(path: Path) -> str:
    """Return lower-case hex SHA-256 of *path*.

    Returns empty string on any I/O error rather than raising.
    """
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
) -> tuple[bool, str]:
    """Verify model presence/hash and return ``(ok, reason)``.

    Reasons include:
    ``ok``, ``unverified``, ``missing``, ``empty``, ``hash_mismatch``,
    ``timeout``, ``cancelled``, ``permission_denied``, ``io_error``,
    ``manifest_error``.
    """
    if not isinstance(entry_id, str) or not entry_id:
        entry_id = "local"
    if models_dir is None:
        models_dir = get_models_dir()

    try:
        manifest = load_manifest(models_dir)
        entry = get_entry(manifest, entry_id)
        filename = entry.get("file", "")
        if not filename:
            return False, "missing"
        path = models_dir / filename
        if not path.exists():
            return False, "missing"
        if path.stat().st_size == 0:
            return False, "empty"
        expected = entry.get("sha256", "").strip().lower()
        if not expected:
            if progress_cb is not None:
                try:
                    progress_cb(100)
                except Exception:
                    pass
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


def verify_model_file(models_dir: Optional[Path] = None,
                      entry_id: str = "local",
                      *,
                      timeout_s: Optional[float] = None,
                      retries: int = 0,
                      progress_cb: Optional[Callable[[int], None]] = None,
                      cancel_event: Optional[threading.Event] = None) -> bool:
    if not isinstance(entry_id, str) or not entry_id:
        entry_id = "local"
    """Return True when the model file exists and SHA-256 matches manifest.

    A missing sha256 in the manifest (e.g. manual import) returns True so
    user-imported files are usable without requiring a network verify round.
    """
    ok, _ = verify_model_file_with_reason(
        models_dir=models_dir,
        entry_id=entry_id,
        timeout_s=timeout_s,
        retries=retries,
        progress_cb=progress_cb,
        cancel_event=cancel_event,
    )
    return ok


# LLMProvider abstract interface.

class LLMProvider(abc.ABC):
    """Minimal interface every local inference backend must implement.

    Subclasses: ``LlamaCppProvider`` (current).
    Future: ``OllamaProvider``, ``ONNXProvider``, …
    """

    @abc.abstractmethod
    def is_available(self) -> bool:
        """True when loaded and ready."""

    @abc.abstractmethod
    def load(self) -> None:
        """Initialise; may raise ImportError / MemoryError / RuntimeError."""

    @abc.abstractmethod
    def unload(self) -> None:
        """Release all resources."""

    @abc.abstractmethod
    def generate(self, messages: list,
                 temperature: float = 0.3,
                 max_tokens: int = 1024) -> str:
        """Run inference; return assistant reply as plain string."""


# LlamaCppProvider.

class LlamaCppProvider(LLMProvider):
    """llama-cpp-python backend — lazy, thread-safe, ChatML prompt format.

    Auto-installs ``llama-cpp-python`` on first ``load()`` call so users
    never need to open a terminal.
    """

    def __init__(self, model_path: Path,
                 n_ctx: int = _N_CTX,
                 n_threads: int = _N_THREADS,
                 n_gpu_layers: int = 0) -> None:
        self._model_path   = Path(model_path) if model_path else Path()
        self._n_ctx        = max(512, int(n_ctx))
        self._n_threads    = max(1, int(n_threads))
        self._n_gpu_layers = max(0, int(n_gpu_layers))
        self._llama: Any   = None
        self._lock         = threading.Lock()

    def is_available(self) -> bool:
        with self._lock:
            return self._llama is not None

    def load(self) -> None:
        with self._lock:
            if self._llama is not None:
                return
            # Auto-install llama-cpp-python if absent.
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
                raise FileNotFoundError(
                    f"Model file not found: {self._model_path}")
            try:
                self._llama = Llama(
                    model_path=str(self._model_path),
                    n_ctx=self._n_ctx,
                    n_threads=self._n_threads,
                    n_gpu_layers=self._n_gpu_layers,
                    verbose=False,
                )
            except MemoryError:
                raise
            except Exception as exc:
                raise RuntimeError(f"Model load failed: {exc}") from exc

    def unload(self) -> None:
        with self._lock:
            self._llama = None

    def generate(self, messages: list,
                 temperature: float = 0.3,
                 max_tokens: int = 1024) -> str:
        """Build ChatML prompt, run inference, strip thinking tags."""
        with self._lock:
            if self._llama is None:
                raise RuntimeError("Provider not loaded — call load() first.")
            if not isinstance(messages, (list, tuple)) or not messages:
                raise ValueError("messages must be a non-empty list.")
            # Build ChatML prompt (SmallThinker / Qwen / GLM compatible).
            parts = []
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                role    = str(msg.get("role", "user"))
                content = str(msg.get("content", ""))
                parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
            parts.append("<|im_start|>assistant\n")
            prompt = "\n".join(parts)
            try:
                result = self._llama(
                    prompt,
                    max_tokens=max(1, int(max_tokens)),
                    temperature=float(temperature),
                    stop=["<|im_end|>", "<|im_start|>"],
                    echo=False,
                )
                raw = result["choices"][0]["text"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected llama output format: {exc}") from exc
            # Strip thinking-process tags before returning.
            return _strip_thinking(raw)


# LocalModelService orchestration.

class LocalModelService:
    """Process singleton: lazy provider load, thread-safe, one instance."""

    _instance:       Optional["LocalModelService"] = None
    _singleton_lock: threading.Lock = threading.Lock()

    def __init__(self, models_dir: Optional[Path] = None) -> None:
        self._models_dir = models_dir or get_models_dir()
        self._provider: Optional[LLMProvider] = None
        self._load_lock  = threading.Lock()

    # Singleton lifecycle.

    @classmethod
    def get(cls, _services=None) -> "LocalModelService":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Destroy singleton (e.g. after re-download or settings change)."""
        with cls._singleton_lock:
            if cls._instance and cls._instance._provider:
                try:
                    cls._instance._provider.unload()
                except Exception:
                    pass
            cls._instance = None

    # Status helpers.

    def is_model_ready(self) -> bool:
        """True when the active model file exists and SHA-256 matches."""
        try:
            return verify_model_file(self._models_dir)
        except Exception:
            return False

    def is_model_present(self) -> bool:
        """True when any GGUF file exists (regardless of SHA-256 state)."""
        try:
            manifest = load_manifest(self._models_dir)
            entry    = get_entry(manifest, "local")
            path     = self._models_dir / entry.get("file", "")
            return bool(path) and path.exists() and path.stat().st_size > 0
        except Exception:
            return False

    # Lazy provider loading.

    def load_provider(self, services=None) -> LLMProvider:
        """Return loaded provider; raises on failure.

        This is the *only* place the Llama instance is created.  It is
        intentionally NOT called at startup — only when inference is first
        requested (lazy loading).
        """
        with self._load_lock:
            if services is not None and not is_local_model_enabled(services):
                raise RuntimeError("ai_assist.local_model_not_running")
            if self._provider and self._provider.is_available():
                return self._provider
            manifest = load_manifest(self._models_dir)
            entry    = get_entry(manifest, "local")
            path     = self._models_dir / entry.get("file", MODEL_FILENAME)
            if not path or not path.exists():
                raise FileNotFoundError(
                    f"Model file not found: {path}\n"
                    "Please download it in Settings → AI."
                )
            # Use per-model n_ctx from catalog (falls back to default _N_CTX)
            cat_entry = get_catalog_entry(
                entry.get("id", "local"), self._models_dir)
            n_ctx = int(cat_entry.get("n_ctx", _N_CTX))
            provider = LlamaCppProvider(path, n_ctx=n_ctx)
            provider.load()          # may raise MemoryError / RuntimeError
            self._provider = provider
            return provider

    def unload_provider(self) -> None:
        with self._load_lock:
            if self._provider:
                self._provider.unload()
                self._provider = None

    def is_provider_loaded(self) -> bool:
        with self._load_lock:
            return self._provider is not None and self._provider.is_available()

    # Inference.

    def generate(self, messages: list,
                 temperature: float = 0.3,
                 max_tokens: int = 1024,
                 services=None) -> str:
        """Load provider lazily, run inference, return stripped reply."""
        if not messages:
            raise ValueError("messages must not be empty.")
        provider = self.load_provider(services=services)
        return provider.generate(messages,
                                  temperature=temperature,
                                  max_tokens=max_tokens)

    # File management.

    def import_gguf(self, source_path: str,
                    entry_id: str = "local") -> Path:
        """Copy a user-supplied .gguf file into models/ and update state.

        If *entry_id* resolves to "local" (the active entry) and the source
        filename does not match any catalog entry, the file is stored under
        its original name and a new catalog+manifest entry is created for it
        so that nothing is silently renamed or misidentified.

        Parameters
        ----------
        source_path:
            Full path to the source .gguf file.
        entry_id:
            Catalog entry id to associate with the import, or ``"local"``
            to use the currently active entry.  Pass ``"__new__"`` to
            always create a fresh entry based on the source filename.
        """
        src_p = Path(source_path)
        if not src_p.exists():
            raise FileNotFoundError(f"File not found: {source_path}")
        if src_p.stat().st_size == 0:
            raise ValueError(f"File is empty: {source_path}")
        self._models_dir.mkdir(parents=True, exist_ok=True)

        src_filename = src_p.name
        catalog      = load_catalog(self._models_dir)

        # Resolve which catalog entry to use.
        if entry_id == "__new__":
            matched = None
        else:
            resolved_id = get_entry(
                load_manifest(self._models_dir), entry_id
            ).get("id", "")
            matched = next(
                (e for e in catalog if e.get("id") == resolved_id), None)

        if matched is None:
            # Check if source filename matches any catalog entry by file name.
            matched = next(
                (e for e in catalog
                 if e.get("file", "").lower() == src_filename.lower()),
                None,
            )

        if matched is not None:
            # Known catalog model — use its canonical filename.
            dest = self._models_dir / matched["file"]
            target_id = matched["id"]
        else:
            # Unknown model — keep original filename and create a custom entry.
            dest      = self._models_dir / src_filename
            target_id = f"custom_{src_p.stem}"
            # Add to catalog.json so future loads recognise it.
            new_cat_entry = {
                "id":      target_id,
                "label":   src_p.stem,
                "file":    src_filename,
                "url":     "",
                "sha256":  "",
                "size_mb": int(src_p.stat().st_size / 1_048_576),
                "ram_gb":  0,
                "n_ctx":   8192,
                "default": False,
                "desc":    {"en_US": f"Manually imported: {src_filename}"},
                "pros":    {"en_US": "✓ Custom model"},
            }
            catalog.append(new_cat_entry)
            _save_catalog(catalog, self._models_dir)

        shutil.copy2(str(src_p), str(dest))
        sha = sha256_of_file(dest)

        # Ensure a manifest entry exists for this id.
        manifest = load_manifest(self._models_dir)
        ids_in_manifest = {e.get("id") for e in manifest}
        if target_id not in ids_in_manifest:
            manifest.append({
                "id":     target_id,
                "file":   dest.name,
                "url":    "",
                "sha256": "",
                "active": False,
            })
            _write_manifest(manifest, self._models_dir)

        update_sha256_in_manifest(sha, self._models_dir, target_id)
        set_active_entry(target_id, self._models_dir)
        return dest

    def delete_model(self, entry_id: str = "local") -> None:
        """Unload provider and delete the GGUF file."""
        self.unload_provider()
        delete_model_file(entry_id, self._models_dir)

    def switch_model(self, new_entry_id: str) -> None:
        """Switch active model; raises FileExistsError if current is verified."""
        current_id = get_active_entry_id(self._models_dir)
        if current_id == new_entry_id:
            return
        if self.is_model_ready():
            raise FileExistsError(
                f"Model '{current_id}' is already downloaded.  "
                "Delete it before switching to another model."
            )
        set_active_entry(new_entry_id, self._models_dir)
        self.unload_provider()


# Decision helpers.

def should_use_local_model(services) -> bool:
    """Return True when local model is enabled AND file passes SHA-256.

    Centralised here (no Qt imports) so it can be unit-tested in isolation.
    Catches all exceptions to guarantee a boolean return.
    """
    if services is None:
        return False
    try:
        if not is_local_model_enabled(services):
            return False
        return verify_model_file()
    except Exception:
        return False


def is_local_model_enabled(services) -> bool:
    """Return True when the local model global switch is enabled."""
    if services is None:
        return False
    try:
        return str(services.get_setting("local_model_enabled", "0")) == "1"
    except Exception:
        return False


# Backward-compatible DownloadManager shim delegating to DownloadController.

class DownloadManager:
    """Thin shim: redirects to DownloadController for backward compatibility."""

    _instance: Optional["DownloadManager"] = None
    _lock:     threading.Lock = threading.Lock()

    @classmethod
    def get(cls, _models_dir=None) -> "DownloadManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset(cls) -> None:
        from services.download_controller import DownloadController
        DownloadController.reset()
        with cls._lock:
            cls._instance = None

    @property
    def is_running(self) -> bool:
        from services.download_controller import DownloadController
        return DownloadController.get().is_running

    def get_progress(self) -> tuple:
        from services.download_controller import DownloadController
        return DownloadController.get().get_progress()

    def download_model(
        self,
        progress_cb=None,
        status_cb=None,
        done_cb=None,
        error_cb=None,
        entry_id: str = "local",
    ) -> None:
        from services.download_controller import DownloadController
        DownloadController.get().start(
            entry_id=entry_id,
            progress_cb=progress_cb,
            status_cb=status_cb,
            done_cb=done_cb,
            error_cb=error_cb,
        )

    def cancel(self) -> None:
        from services.download_controller import DownloadController
        DownloadController.get().cancel()
