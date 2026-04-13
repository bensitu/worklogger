"""Automatic dependency installer for optional runtime packages.

Packages needed for local model inference (llama-cpp-python, httpx) are not
listed in requirements.txt because they are large / platform-specific.
This module installs them on first use so the app ships as a single package
and users never need to open a terminal.

Thread-safety: all public functions acquire a module-level lock.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
import threading

_lock = threading.Lock()

# Packages that cannot be auto-installed (require manual OS-level setup).
_UNSUPPORTED: set = set()

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def ensure(*packages: str) -> None:
    """Ensure every listed package is importable; install those that aren't.

    *packages* are pip package specifiers, e.g. ``"httpx>=0.27.0"``.
    Raises ``ImportError`` if any package cannot be installed.
    """
    with _lock:
        failures = []
        for spec in packages:
            import_name = _spec_to_import_name(spec)
            if _is_importable(import_name):
                continue
            ok, err = _pip_install(spec)
            if not ok:
                failures.append(f"{spec}: {err}")
        if failures:
            raise ImportError(
                "Could not auto-install required packages:\n"
                + "\n".join(f"  • {f}" for f in failures)
            )


def is_available(import_name: str) -> bool:
    """Return True when *import_name* can be imported (no side effects)."""
    return _is_importable(import_name)


# ──────────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────────

def _spec_to_import_name(spec: str) -> str:
    """``"httpx>=0.27.0"`` → ``"httpx"``; ``"llama-cpp-python"`` → ``"llama_cpp"``."""
    base = spec.split(">=")[0].split("==")[0].split(">")[0].strip()
    # Map known hyphenated package names to their import names.
    mapping = {
        "llama-cpp-python": "llama_cpp",
        "portalocker":      "portalocker",
            }
    return mapping.get(base, base.replace("-", "_"))


def _is_importable(import_name: str) -> bool:
    spec = importlib.util.find_spec(import_name)  # type: ignore[attr-defined]
    return spec is not None


def _pip_install(spec: str) -> tuple[bool, str]:
    """Run ``pip install <spec>`` and return ``(success, stderr_text)``."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", spec, "--quiet"],
            capture_output=True,
            timeout=300,
        )
        if result.returncode == 0:
            # Invalidate any cached negative import results.
            importlib.invalidate_caches()
            return True, ""
        return False, result.stderr.decode(errors="replace").strip()
    except Exception as exc:
        return False, str(exc)


def ensure_download_deps() -> None:
    """Install portalocker and httpx if not present.

    Note: pywin32 is intentionally excluded — it must be installed via the
    system package manager on Windows (e.g. conda or the official installer).
    portalocker will fall back to its LockBase implementation automatically
    on environments without win32 support.
    """
    ensure("portalocker>=2.8.0", "httpx>=0.27.0")


def ensure_inference_deps() -> None:
    """Install llama-cpp-python (CPU-only wheel by default)."""
    ensure("llama-cpp-python>=0.2.90")
