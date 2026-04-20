# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WorkLogger 2.0.

Build (from project root):
    pip install pyinstaller llama-cpp-python httpx portalocker
    pyinstaller worklogger.spec

Packaging strategy
------------------
* GGUF model files are NOT bundled — they are downloaded on demand to the
  models/ folder next to the executable.
* catalog.json IS bundled and copied to the user's models/ on first run.
"""

import sys
import os
import subprocess
import importlib.util
from pathlib import Path
import certifi

block_cipher = None
ROOT_DIR = Path(globals().get("SPECPATH", os.getcwd())).resolve()
LOCALES_DIR = ROOT_DIR / "worklogger" / "locales"
I18N_COMPILE_SCRIPT = ROOT_DIR / "scripts" / "i18n_compile.py"
I18N_LANGS = ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW")


def _ensure_i18n_catalogs() -> None:
    subprocess.run([sys.executable, str(I18N_COMPILE_SCRIPT)], check=True)
    missing: list[str] = []
    for lang in I18N_LANGS:
        mo_path = LOCALES_DIR / lang / "LC_MESSAGES" / "messages.mo"
        if not mo_path.is_file():
            missing.append(str(mo_path))
    if missing:
        raise RuntimeError(
            "Missing compiled gettext catalogs:\n" + "\n".join(missing)
        )


_ensure_i18n_catalogs()


def _certifi_cacert_data_entry() -> tuple[str, str]:
    cert_path = Path(certifi.where()).resolve()
    if not cert_path.is_file():
        raise RuntimeError(f"certifi bundle not found: {cert_path}")
    return (str(cert_path), "certifi")


CERTIFI_CACERT_DATA = _certifi_cacert_data_entry()


# ---------------------------------------------------------------------------
# Safe collection helpers — gracefully skip if a package is not installed.
# ---------------------------------------------------------------------------

def _collect(pkg: str):
    """Collect all data files and dynamic libraries for *pkg*.
    Returns (data_list, bin_list); both empty if package is absent.
    """
    try:
        from PyInstaller.utils.hooks import collect_all
        datas, binaries, hiddenimports = collect_all(pkg)
        return datas, binaries
    except Exception:
        pass
    try:
        from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs
        return collect_data_files(pkg), collect_dynamic_libs(pkg)
    except Exception:
        return [], []


def _collect_submodules(pkg: str):
    try:
        from PyInstaller.utils.hooks import collect_submodules
        return collect_submodules(pkg)
    except Exception:
        return []


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


# Collect llama_cpp (large; includes native .so/.dll and Metal shaders)
_llama_data, _llama_bins = _collect("llama_cpp")

# Collect httpx and portalocker (pure-Python but have data files)
_httpx_data,      _httpx_bins      = _collect("httpx")
_portalocker_data, _portalocker_bins = _collect("portalocker")

# Hidden submodules that PyInstaller may miss
_llama_hidden      = _collect_submodules("llama_cpp")
_httpx_hidden      = _collect_submodules("httpx")
_portalocker_hidden = _collect_submodules("portalocker")

_optional_hidden = [
    pkg for pkg in (
        "llama_cpp",
        "httpx",
        "portalocker",
        "numpy",
        "httpcore",
        "anyio",
        "sniffio",
        "certifi",
        "h11",
    )
    if _module_exists(pkg)
]


a = Analysis(
    ["worklogger/main.py"],
    pathex=["."],
    binaries=_llama_bins + _httpx_bins + _portalocker_bins,
    datas=[
        # Application assets
        ("worklogger/assets",                               "assets"),
        # i18n translation catalogs
        ("worklogger/locales",                              "locales"),
        # TLS CA bundle used by urllib-based update check
        CERTIFI_CACERT_DATA,
        # Built-in report templates
        ("worklogger/templates/en_US",                          "templates/en_US"),
        ("worklogger/templates/ja_JP",                          "templates/ja_JP"),
        ("worklogger/templates/zh_CN",                          "templates/zh_cn"),
        ("worklogger/templates/zh_TW",                          "templates/zh_tw"),
        ("worklogger/templates/ko_KR",                          "templates/ko_KR"),
        ("worklogger/templates/custom/Sample_1000000000000.json",
                                                            "templates/custom"),
        # Local model catalog
        ("worklogger/models/catalog.json",                  "models"),
    ] + _llama_data + _httpx_data + _portalocker_data,
    hiddenimports=[
        "sqlite3",
        "holidays",
        "holidays.countries",
        "tzlocal",
        "PySide6.QtPrintSupport",
        # Local model subsystem
        "services.dep_installer",
        "services.download_controller",
        "services.local_model_service",
        # Optional runtime deps (included when present in the build venv)
    ] + _optional_hidden + _llama_hidden + _httpx_hidden + _portalocker_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # Large ML frameworks not used by this app
        "torch", "tensorflow", "jax",
        "pandas", "matplotlib", "scipy", "sklearn",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WorkLogger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="worklogger/assets/worklogger.ico",
)

# macOS .app bundle
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="WorkLogger",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="WorkLogger.app",
        icon="worklogger/assets/worklogger.icns",
        bundle_identifier="dev.worklogger.app.v1",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "2.2.1",
            "CFBundleVersion": "7",
        },
    )
