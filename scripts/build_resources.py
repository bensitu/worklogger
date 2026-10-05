"""Explicit, data-free resource manifest for desktop packaging."""

from pathlib import Path

from worklogger.__about__ import APP_AUTHOR, APP_NAME, APP_VERSION


def bundled_resources(root: Path) -> list[tuple[str, str]]:
    package = root / "worklogger"
    resources: list[tuple[str, str]] = []
    for directory in (package / "assets", package / "presentation/theme/qss"):
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                if path.suffix.lower() == ".avif":
                    raise ValueError("AVIF is not a supported runtime asset")
                resources.append((str(path), path.parent.relative_to(root).as_posix()))
    for language in ("en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR"):
        path = package / "locales" / language / "LC_MESSAGES" / "messages.mo"
        if not path.is_file():
            raise FileNotFoundError(f"Compile translations before packaging: {path}")
        resources.append((str(path), path.parent.relative_to(root).as_posix()))
    return resources


def executable_icon(root: Path, platform: str) -> str | None:
    if platform.startswith("win"):
        return str(root / "worklogger/assets/icons/worklogger.ico")
    if platform == "darwin":
        return str(root / "worklogger/assets/icons/worklogger.icns")
    return None


def windows_version_resource():
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable,
        VarFileInfo, VarStruct, VSVersionInfo,
    )

    version = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
    fields = {
        "CompanyName": APP_AUTHOR, "FileDescription": APP_NAME,
        "FileVersion": APP_VERSION, "InternalName": APP_NAME,
        "OriginalFilename": f"{APP_NAME}.exe", "ProductName": APP_NAME,
        "ProductVersion": APP_VERSION,
    }
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3F,
                          flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
        kids=[StringFileInfo([StringTable("040904B0", [
            StringStruct(key, value) for key, value in fields.items()
        ])]), VarFileInfo([VarStruct("Translation", [1033, 1200])])],
    )
