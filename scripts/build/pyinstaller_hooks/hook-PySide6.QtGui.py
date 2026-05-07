from pathlib import Path

from PyInstaller import compat
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)

if compat.is_linux:
    binaries = [
        entry
        for entry in binaries
        if not (
            Path(str(entry[0])).name == "libqtiff.so"
            and "imageformats" in str(entry[1]).replace("\\", "/")
        )
    ]
