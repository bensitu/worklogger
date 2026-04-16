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

block_cipher = None


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


# Collect llama_cpp (large; includes native .so/.dll and Metal shaders)
_llama_data, _llama_bins = _collect("llama_cpp")

# Collect httpx and portalocker (pure-Python but have data files)
_httpx_data,      _httpx_bins      = _collect("httpx")
_portalocker_data, _portalocker_bins = _collect("portalocker")

# Hidden submodules that PyInstaller may miss
_llama_hidden      = _collect_submodules("llama_cpp")
_httpx_hidden      = _collect_submodules("httpx")
_portalocker_hidden = _collect_submodules("portalocker")


a = Analysis(
    ["worklogger/main.py"],
    pathex=["."],
    binaries=_llama_bins + _httpx_bins + _portalocker_bins,
    datas=[
        # Application assets
        ("worklogger/assets",                               "assets"),
        # Built-in report templates
        ("worklogger/templates/en",                         "templates/en"),
        ("worklogger/templates/ja",                         "templates/ja"),
        ("worklogger/templates/zh_cn",                      "templates/zh_cn"),
        ("worklogger/templates/zh_tw",                      "templates/zh_tw"),
        ("worklogger/templates/ko",                         "templates/ko"),
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
        # Bundled runtime deps
        "llama_cpp",
        "httpx",
        "httpx._client",
        "httpx._transports",
        "httpx._transports.default",
        "portalocker",
        "portalocker.utils",
        "portalocker.exceptions",
        "numpy",
        # httpx back-end
        "httpcore",
        "anyio",
        "sniffio",
        "certifi",
        "h11",
    ] + _llama_hidden + _httpx_hidden + _portalocker_hidden,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    name="WorkLogger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="worklogger/assets/worklogger.ico",
)

# macOS .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="WorkLogger.app",
        icon="worklogger/assets/worklogger.icns",
        bundle_identifier="dev.worklogger.app.v1",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "2.1.0",
            "CFBundleVersion": "5",
        },
    )
