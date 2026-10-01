"""Explicit, data-free resource manifest for desktop packaging."""

from pathlib import Path


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
