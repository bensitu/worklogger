# PyInstaller builds are produced on their target operating system.
import importlib.util
import os
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from scripts.build_resources import bundled_resources, executable_icon

datas = bundled_resources(root)
hiddenimports = collect_submodules("worklogger") + collect_submodules("holidays")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("icalendar") + collect_submodules("recurring_ical_events")
datas += collect_data_files("icalendar")
datas += collect_data_files("tzlocal") + collect_data_files("certifi")
binaries = []
for package in ("tzdata", "llama_cpp"):
    if importlib.util.find_spec(package) is not None:
        package_data, package_binaries, package_imports = collect_all(package)
        datas += package_data
        binaries += package_binaries
        hiddenimports += package_imports

analysis = Analysis(
    [str(root / "worklogger/main.py")],
    pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2"], noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive, analysis.scripts, [], exclude_binaries=True, name="WorkLogger",
    debug=False, strip=False, upx=False,
    console=os.environ.get("WORKLOGGER_BUILD_CONSOLE") == "1",
    icon=executable_icon(root, sys.platform),
)
collection = COLLECT(
    executable, analysis.binaries, analysis.datas,
    strip=False, upx=False, name="WorkLogger",
)
if sys.platform == "darwin":
    application = BUNDLE(
        collection, name="WorkLogger.app",
        icon=executable_icon(root, sys.platform),
        bundle_identifier="io.worklogger.desktop",
        info_plist={"NSHighResolutionCapable": True},
    )
