"""Dependency checker / installer for optional runtime packages.

Frozen (PyInstaller) builds
----------------------------
When running as a packaged .exe or .app, llama-cpp-python, httpx and
portalocker are bundled directly into the executable by the build spec.
Auto-installation is skipped in this case; missing packages surface as a
clear ImportError with instructions for the end-user.

Source / development runs
--------------------------
Packages not yet installed are installed via ``pip`` on first use so
developers and testers never need to run a separate setup step.

Thread-safety: all public functions acquire a module-level lock.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import threading

_lock = threading.Lock()


# Public API.

def ensure(*packages: str) -> None:
    """Ensure every listed package is importable.

    In a **frozen** build the packages must already be bundled — pip cannot
    install new packages into a read-only .exe/.app archive.  If a bundled
    package is somehow missing, a clear ``ImportError`` is raised immediately
    instead of attempting (and silently failing) a pip install.

    In a **source** run packages are installed via ``pip`` if absent.

    *packages* are pip package specifiers, e.g. ``"httpx>=0.27.0"``.
    """
    with _lock:
        frozen = getattr(sys, "frozen", False)
        failures: list[str] = []
        for spec in packages:
            import_name = _spec_to_import_name(spec)
            if _is_importable(import_name):
                continue
            if frozen:
                # Bundled package not found — cannot pip-install in frozen app.
                failures.append(
                    f"{spec} (package should be bundled — "
                    "please re-install WorkLogger)"
                )
            else:
                ok, err = _pip_install(spec)
                if not ok:
                    failures.append(f"{spec}: {err}")
        if failures:
            raise ImportError(
                "Required packages are not available:\n"
                + "\n".join(f"  • {f}" for f in failures)
            )


def is_available(import_name: str) -> bool:
    """Return True when *import_name* can be imported (no side effects)."""
    return _is_importable(import_name)


# Internals.

def _spec_to_import_name(spec: str) -> str:
    """``"httpx>=0.27.0"`` → ``"httpx"``;
    ``"llama-cpp-python"`` → ``"llama_cpp"``."""
    base = spec.split(">=")[0].split("==")[0].split(">")[0].strip()
    mapping = {
        "llama-cpp-python": "llama_cpp",
        "portalocker":      "portalocker",
    }
    return mapping.get(base, base.replace("-", "_"))


def _is_importable(import_name: str) -> bool:
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def _pip_install(spec: str) -> tuple:
    """Run ``pip install <spec>``; return ``(success, stderr_text)``."""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", spec, "--quiet"],
            capture_output=True,
            timeout=300,
        )
        if result.returncode == 0:
            importlib.invalidate_caches()
            return True, ""
        return False, result.stderr.decode(errors="replace").strip()
    except Exception as exc:
        return False, str(exc)


def ensure_download_deps() -> None:
    """Ensure portalocker and httpx are available for the model downloader."""
    ensure("portalocker>=2.8.0", "httpx>=0.27.0")


def ensure_inference_deps() -> None:
    """Ensure llama-cpp-python is available for local inference."""
    ensure("llama-cpp-python>=0.2.90")
