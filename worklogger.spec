# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WorkLogger.

Packaging strategy
------------------
* GGUF model files are not bundled; they are downloaded on demand.
* catalog.json is bundled and copied to the user models directory on first run.
* Build targets are explicit by platform:
  - macOS: .app bundle (COLLECT + BUNDLE)
  - Windows/other: onefile executable
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import certifi

block_cipher = None

APP_NAME = "WorkLogger"
PLATFORM = sys.platform
ROOT_DIR = Path(globals().get("SPECPATH", os.getcwd())).resolve()
WORKLOGGER_DIR = ROOT_DIR / "worklogger"
ASSETS_DIR = WORKLOGGER_DIR / "assets"
TEMPLATES_DIR = WORKLOGGER_DIR / "templates"
LOCALES_DIR = WORKLOGGER_DIR / "locales"
MODELS_DIR = WORKLOGGER_DIR / "models"
I18N_COMPILE_SCRIPT = ROOT_DIR / "scripts" / "i18n" / "i18n_compile.py"
I18N_LANGS = ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW")
UPX_ENABLED = True


def _require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise RuntimeError(f"Missing required {label}: {path}")
    return path


def _resolve_existing_dir(label: str, *relative_candidates: str) -> Path:
    for rel in relative_candidates:
        candidate = ROOT_DIR / rel
        if candidate.is_dir():
            return candidate
    joined = ", ".join(str(ROOT_DIR / rel) for rel in relative_candidates)
    raise RuntimeError(f"Missing required {label}. Checked: {joined}")


def _ensure_i18n_catalogs() -> None:
    _require_file(I18N_COMPILE_SCRIPT, "i18n compile script")
    subprocess.run([sys.executable, str(I18N_COMPILE_SCRIPT)], check=True)
    missing: list[str] = []
    for lang in I18N_LANGS:
        mo_path = LOCALES_DIR / lang / "LC_MESSAGES" / "messages.mo"
        if not mo_path.is_file():
            missing.append(str(mo_path))
    if missing:
        raise RuntimeError("Missing compiled gettext catalogs:\n" + "\n".join(missing))


def _certifi_cacert_data_entry() -> tuple[str, str]:
    cert_path = Path(certifi.where()).resolve()
    if not cert_path.is_file():
        raise RuntimeError(f"certifi bundle not found: {cert_path}")
    return str(cert_path), "certifi"


def _collect(pkg: str):
    """Collect package data files and native binaries if package is installed."""
    try:
        from PyInstaller.utils.hooks import collect_all

        datas, binaries, _hidden = collect_all(pkg)
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


_ensure_i18n_catalogs()

CERTIFI_CACERT_DATA = _certifi_cacert_data_entry()
ICON_ICO = _require_file(ASSETS_DIR / "worklogger.ico", "Windows icon") if PLATFORM == "win32" else None
ICON_ICNS = _require_file(ASSETS_DIR / "worklogger.icns", "macOS icon") if PLATFORM == "darwin" else None
TEMPLATE_EN_US_DIR = _resolve_existing_dir("en_US templates", "worklogger/templates/en_US")
TEMPLATE_JA_JP_DIR = _resolve_existing_dir("ja_JP templates", "worklogger/templates/ja_JP")
TEMPLATE_KO_KR_DIR = _resolve_existing_dir("ko_KR templates", "worklogger/templates/ko_KR")
TEMPLATE_ZH_CN_DIR = _resolve_existing_dir(
    "zh_CN templates",
    "worklogger/templates/zh_cn",
    "worklogger/templates/zh_CN",
)
TEMPLATE_ZH_TW_DIR = _resolve_existing_dir(
    "zh_TW templates",
    "worklogger/templates/zh_tw",
    "worklogger/templates/zh_TW",
)
TEMPLATE_CUSTOM_SAMPLE = _require_file(
    TEMPLATES_DIR / "custom" / "Sample_1000000000000.json",
    "custom template sample",
)
CATALOG_JSON = _require_file(MODELS_DIR / "catalog.json", "model catalog")

# Optional package collections.
_llama_data, _llama_bins = _collect("llama_cpp") if _module_exists("llama_cpp") else ([], [])
_httpx_data, _httpx_bins = _collect("httpx") if _module_exists("httpx") else ([], [])
_portalocker_data, _portalocker_bins = _collect("portalocker") if _module_exists("portalocker") else ([], [])

_llama_hidden = _collect_submodules("llama_cpp") if _module_exists("llama_cpp") else []
_httpx_hidden = _collect_submodules("httpx") if _module_exists("httpx") else []
_portalocker_hidden = _collect_submodules("portalocker") if _module_exists("portalocker") else []

_optional_hidden = [
    pkg
    for pkg in (
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
    [str(WORKLOGGER_DIR / "main.py")],
    pathex=[str(ROOT_DIR), str(WORKLOGGER_DIR)],
    binaries=_llama_bins + _httpx_bins + _portalocker_bins,
    datas=[
        (str(ASSETS_DIR), "assets"),
        (str(LOCALES_DIR), "locales"),
        CERTIFI_CACERT_DATA,
        (str(TEMPLATE_EN_US_DIR), "templates/en_US"),
        (str(TEMPLATE_JA_JP_DIR), "templates/ja_JP"),
        (str(TEMPLATE_ZH_CN_DIR), "templates/zh_CN"),
        (str(TEMPLATE_ZH_TW_DIR), "templates/zh_TW"),
        (str(TEMPLATE_KO_KR_DIR), "templates/ko_KR"),
        (str(TEMPLATE_CUSTOM_SAMPLE), "templates/custom"),
        (str(CATALOG_JSON), "models"),
    ]
    + _llama_data
    + _httpx_data
    + _portalocker_data,
    hiddenimports=[
        "sqlite3",
        "holidays",
        "holidays.countries",
        "tzlocal",
        "PySide6.QtPrintSupport",
        "services.dep_installer",
        "services.download_controller",
        "services.local_model_service",
    ]
    + _optional_hidden
    + _llama_hidden
    + _httpx_hidden
    + _portalocker_hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "torch",
        "tensorflow",
        "jax",
        "pandas",
        "matplotlib",
        "scipy",
        "sklearn",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if PLATFORM == "darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=UPX_ENABLED,
        console=False,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.zipfiles,
        a.datas,
        strip=False,
        upx=UPX_ENABLED,
        name=APP_NAME,
    )

    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=str(ICON_ICNS),
        bundle_identifier="dev.worklogger.app.v1",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "2.2.2",
            "CFBundleVersion": "8",
        },
    )
elif PLATFORM == "win32":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        exclude_binaries=False,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=UPX_ENABLED,
        console=False,
        icon=str(ICON_ICO),
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        exclude_binaries=False,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=UPX_ENABLED,
        console=False,
    )
