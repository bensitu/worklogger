# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for WorkLogger.

Packaging strategy
------------------
* GGUF model files are not bundled; they are downloaded on demand.
* model_catalog.json is a GitHub-hosted remote catalog and is not bundled.
* Build targets are explicit by platform:
  - macOS: .app bundle (COLLECT + BUNDLE)
  - Windows: onefile executable
  - Linux: onefile executable
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import certifi

block_cipher = None

APP_NAME = "WorkLogger"
APP_VERSION = "3.3.1"
PLATFORM = sys.platform
ROOT_DIR = Path(globals().get("SPECPATH", os.getcwd())).resolve()
WORKLOGGER_DIR = ROOT_DIR / "worklogger"
ASSETS_DIR = WORKLOGGER_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
TEMPLATES_DIR = WORKLOGGER_DIR / "templates"
LOCALES_DIR = WORKLOGGER_DIR / "locales"
I18N_COMPILE_SCRIPT = ROOT_DIR / "scripts" / "i18n" / "i18n_compile.py"
I18N_LANGS = ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW")
HOOKS_DIR = ROOT_DIR / "scripts" / "build" / "pyinstaller_hooks"
BUILD_LOGS_DIR = ROOT_DIR / "build_logs"
WARN_FILE = BUILD_LOGS_DIR / "warn-worklogger.txt"
UPX_ENABLED = True

if str(WORKLOGGER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKLOGGER_DIR))

from config.constants import LANGUAGE_FONT_FILES

REQUIRED_FONT_FILES = tuple(dict.fromkeys(LANGUAGE_FONT_FILES.values()))


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


def _ensure_font_assets() -> None:
    for font_file in REQUIRED_FONT_FILES:
        _require_file(FONTS_DIR / font_file, f"font asset {font_file}")


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


def _collect_submodules(pkg: str, exclude_prefixes: tuple[str, ...] = ()):
    try:
        from PyInstaller.utils.hooks import collect_submodules

        return collect_submodules(
            pkg,
            filter=lambda name: not any(
                name == prefix or name.startswith(prefix + ".")
                for prefix in exclude_prefixes
            ),
        )
    except Exception:
        return []


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _keyring_hiddenimports() -> list[str]:
    candidates = ["keyring", "keyring.backends", "keyring.backends.null"]
    if PLATFORM == "win32":
        candidates.append("keyring.backends.Windows")
    elif PLATFORM == "darwin":
        candidates.append("keyring.backends.macOS")
    elif PLATFORM.startswith("linux"):
        candidates.extend(
            (
                "keyring.backends.SecretService",
                "keyring.backends.chainer",
                "keyring.backends.libsecret",
            )
        )
    return [pkg for pkg in candidates if _module_exists(pkg)]


def _configure_pyinstaller_warning_log() -> None:
    """Write PyInstaller missing-module warnings outside the transient build directory."""
    from PyInstaller.building import build_main as _pyi_build_main
    from PyInstaller.config import CONF

    ignored_names = {
        "_dummy_thread",
        "_frozen_importlib",
        "_frozen_importlib_external",
        "_manylinux",
        "_posixshmem",
        "_posixsubprocess",
        "_pytest",
        "_scproxy",
        "_typeshed",
        "_winreg",
        "annotationlib",
        "asyncio.DefaultEventLoopPolicy",
        "cStringIO",
        "cffi._pycparser",
        "collections.Callable",
        "dateutil.tz.tzfile",
        "dummy_thread",
        "fcntl",
        "grp",
        "importlib_resources",
        "java",
        "java.lang",
        "multiprocessing.AuthenticationError",
        "multiprocessing.BufferTooShort",
        "multiprocessing.TimeoutError",
        "multiprocessing.get_context",
        "multiprocessing.get_start_method",
        "multiprocessing.set_start_method",
        "posix",
        "pwd",
        "pyimod02_importers",
        "readline",
        "resource",
        "setuptools._distutils.msvc9compiler",
        "six.moves",
        "six.moves.range",
        "sitecustomize",
        "StringIO",
        "termios",
        "thread",
        "trove_classifiers",
        "usercustomize",
        "vms_lib",
    }
    ignored_prefixes = (
        "dbus",
        "django",
        "fastapi",
        "gi",
        "h2",
        "huggingface_hub",
        "_typeshed",
        "numpy._core.",
        "numpy._distributor_init_local",
        "numpy.random.RandomState",
        "numpy_distutils",
        "pygments",
        "rich",
        "secretstorage",
        "starlette",
        "starlette_context",
        "trio",
        "win32ctypes.core._",
    )
    ignored_optional_packages = {
        "bcrypt",
        "brotli",
        "brotlicffi",
        "charset_normalizer",
        "click",
        "exceptiongroup",
        "importlib_resources",
        "openai",
        "outcome",
        "psutil",
        "pydantic",
        "pydantic_settings",
        "redis",
        "requests",
        "sniffio",
        "socksio",
        "sse_starlette",
        "threadpoolctl",
        "transformers",
        "uvicorn",
        "uvloop",
        "winloop",
        "yaml",
        "zstandard",
    }
    app_importer_prefixes = ("config", "core", "data", "main", "services", "stores", "ui", "utils")

    def _normalize_missing_name(name: str) -> str:
        return str(name).strip("'\"")

    def _has_app_importer(importers) -> bool:
        for importer, _dep_info in importers:
            root = str(importer).split(".", 1)[0]
            if root in app_importer_prefixes:
                return True
        return False

    def _matches_ignored_prefix(name: str) -> bool:
        for prefix in ignored_prefixes:
            if name == prefix:
                return True
            if prefix.endswith((".", "_")):
                if name.startswith(prefix):
                    return True
            elif name.startswith(prefix + "."):
                return True
        return False

    def _is_ignored_missing(name: str, status: str, importers) -> bool:
        normalized = _normalize_missing_name(name)
        if status == "excluded" or normalized in ignored_names:
            return True
        if _matches_ignored_prefix(normalized):
            return True
        if normalized in ignored_optional_packages and not _has_app_importer(importers):
            return True
        return False

    def _warning_file_for_build() -> Path:
        workpath = Path(CONF.get("workpath", ""))
        build_root = workpath.parent.name
        arch_suffix_by_build_dir = {
            "build_x86": "x86_64",
            "build_arm": "arm64",
        }
        suffix = arch_suffix_by_build_dir.get(build_root)
        if suffix:
            return BUILD_LOGS_DIR / f"warn-worklogger-{suffix}.txt"
        return WARN_FILE

    BUILD_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    CONF["warnfile"] = str(_warning_file_for_build())

    def _write_warnings(self):
        def dependency_description(name, dep_info):
            if not dep_info or dep_info == "direct":
                imptype = 0
            else:
                imptype = dep_info.conditional + 2 * dep_info.function + 4 * dep_info.tryexcept
            return "%s (%s)" % (name, _pyi_build_main.IMPORT_TYPES[imptype])

        miss_toc = []
        for (name, path, status) in self.graph.make_missing_toc():
            importers = self.graph.get_importers(name)
            if not _is_ignored_missing(name, status, importers):
                miss_toc.append((name, path, status, importers))
        warnfile = Path(CONF["warnfile"])
        if not miss_toc:
            if warnfile.exists():
                warnfile.unlink()
            _pyi_build_main.logger.info("No Warnings found; warn-worklogger.txt was not generated.")
            return

        warnfile.parent.mkdir(parents=True, exist_ok=True)
        with open(warnfile, "w", encoding="utf-8") as wf:
            wf.write(_pyi_build_main.WARNFILE_HEADER)
            for (name, _path, status, importers) in miss_toc:
                print(
                    status,
                    "module named",
                    name,
                    "- imported by",
                    ", ".join(dependency_description(importer, data) for importer, data in importers),
                    file=wf,
                )
        _pyi_build_main.logger.info("Warnings written to %s", warnfile)

    _pyi_build_main.Analysis._write_warnings = _write_warnings


_configure_pyinstaller_warning_log()
_ensure_i18n_catalogs()
_ensure_font_assets()

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
# Optional package collections.
_llama_data, _llama_bins = _collect("llama_cpp") if _module_exists("llama_cpp") else ([], [])
_httpx_data, _httpx_bins = _collect("httpx") if _module_exists("httpx") else ([], [])
_portalocker_data, _portalocker_bins = _collect("portalocker") if _module_exists("portalocker") else ([], [])
_keyring_data, _keyring_bins = _collect("keyring") if _module_exists("keyring") else ([], [])
_cryptography_data, _cryptography_bins = _collect("cryptography") if _module_exists("cryptography") else ([], [])
_matplotlib_data, _matplotlib_bins = _collect("matplotlib") if _module_exists("matplotlib") else ([], [])
_reportlab_data, _reportlab_bins = _collect("reportlab") if _module_exists("reportlab") else ([], [])
_pil_data, _pil_bins = _collect("PIL") if _module_exists("PIL") else ([], [])

_llama_hidden = (
    _collect_submodules("llama_cpp", exclude_prefixes=("llama_cpp.server",))
    if _module_exists("llama_cpp") else []
)
_httpx_hidden = []
_portalocker_hidden = (
    _collect_submodules("portalocker", exclude_prefixes=("portalocker.redis",))
    if _module_exists("portalocker") else []
)
_keyring_hidden = _keyring_hiddenimports() if _module_exists("keyring") else []
_core_hidden = []
for _pkg in ("services", "config", "data", "ui", "utils", "stores", "core"):
    _core_hidden += _collect_submodules(_pkg)

_optional_hidden = [
    pkg
    for pkg in (
        "cryptography",
        "cryptography.fernet",
        "jwt",
        "jwt.algorithms",
        "matplotlib",
        "reportlab",
        "PIL",
        "PIL.Image",
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
    binaries=(
        _llama_bins
        + _httpx_bins
        + _portalocker_bins
        + _keyring_bins
        + _cryptography_bins
        + _matplotlib_bins
        + _reportlab_bins
        + _pil_bins
    ),
    datas=[
        (str(ASSETS_DIR), "assets"),
        ("worklogger/locales",                              "locales"),
        CERTIFI_CACERT_DATA,
        (str(TEMPLATE_EN_US_DIR), "templates/en_US"),
        (str(TEMPLATE_JA_JP_DIR), "templates/ja_JP"),
        (str(TEMPLATE_ZH_CN_DIR), "templates/zh_CN"),
        (str(TEMPLATE_ZH_TW_DIR), "templates/zh_TW"),
        (str(TEMPLATE_KO_KR_DIR), "templates/ko_KR"),
        (str(TEMPLATE_CUSTOM_SAMPLE), "templates/custom"),
    ]
    + _llama_data
    + _httpx_data
    + _portalocker_data
    + _keyring_data
    + _cryptography_data
    + _matplotlib_data
    + _reportlab_data
    + _pil_data,
    hiddenimports=[
        "sqlite3",
        "holidays",
        "holidays.countries",
        "tzlocal",
        "PySide6.QtPrintSupport",
        "services.dep_installer",
        "services.download_controller",
        "services.local_model_service",
        "services.report_service",
    ]
    + _core_hidden
    + _optional_hidden
    + _llama_hidden
    + _httpx_hidden
    + _portalocker_hidden
    + _keyring_hidden,
    hookspath=[str(HOOKS_DIR)],
    runtime_hooks=[],
    excludes=[
        "torch",
        "tensorflow",
        "jax",
        "pandas",
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
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
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
