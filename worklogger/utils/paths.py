from __future__ import annotations

import os
import sys
from pathlib import Path

from config.constants import ASSETS_DIR_NAME, FONTS_DIR_NAME


def app_root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def candidate_resource_roots() -> list[Path]:
    candidates: list[Path] = [app_root_dir()]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        root = Path(meipass)
        candidates.extend([root, root / "worklogger"])
    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            candidates.extend([exe_dir, exe_dir.parent / "Resources"])
        except Exception:
            pass

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = os.path.normcase(str(path.resolve(strict=False)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def candidate_assets_dirs() -> list[Path]:
    return [root / ASSETS_DIR_NAME for root in candidate_resource_roots()]


def candidate_fonts_dirs() -> list[Path]:
    return [assets / FONTS_DIR_NAME for assets in candidate_assets_dirs()]


def font_path(filename: str) -> Path | None:
    for fonts_dir in candidate_fonts_dirs():
        path = fonts_dir / filename
        if path.is_file():
            return path
    return None
