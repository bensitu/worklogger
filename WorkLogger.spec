# PyInstaller builds are produced on their target operating system.
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from scripts.build_resources import bundled_resources, executable_icon, windows_version_resource
from worklogger.__about__ import APP_ID, APP_VERSION

datas = bundled_resources(root)
hiddenimports = collect_submodules("worklogger") + collect_submodules("holidays")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("openpyxl") + collect_submodules("et_xmlfile")
runtime_module = lambda name: not any(part in {"test", "tests"} for part in name.split("."))
hiddenimports += collect_submodules("icalendar", filter=runtime_module)
hiddenimports += collect_submodules("recurring_ical_events", filter=runtime_module)
datas += collect_data_files("icalendar", excludes=["tests/**"])
datas += collect_data_files("tzlocal") + collect_data_files("certifi")
binaries = []
packages = ["tzdata"]
if os.environ.get("WORKLOGGER_BUILD_LOCAL_INFERENCE") == "1":
    packages.append("llama_cpp")
for package in packages:
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

analysis = Analysis(
    [str(root / "worklogger/main.py")],
    pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2"] + ([] if "llama_cpp" in packages else ["llama_cpp"]), noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name="WorkLogger",
    debug=False, strip=False, upx=False,
    console=os.environ.get("WORKLOGGER_BUILD_CONSOLE") == "1",
    icon=executable_icon(root, sys.platform),
    version=windows_version_resource() if sys.platform == "win32" else None,
    codesign_identity=os.environ.get("WORKLOGGER_CODESIGN_IDENTITY") or None,
    entitlements_file=os.environ.get("WORKLOGGER_CODESIGN_ENTITLEMENTS") or None,
)
collection = COLLECT(
    executable, analysis.binaries, analysis.datas,
    strip=False, upx=False, name="WorkLogger",
)
if sys.platform == "darwin":
    application = BUNDLE(
        collection, name="WorkLogger.app",
        icon=executable_icon(root, sys.platform),
        bundle_identifier=APP_ID, version=APP_VERSION,
        info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": APP_VERSION},
    )
