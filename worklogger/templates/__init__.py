"""Template management: built-in and custom templates."""

from __future__ import annotations
import os
import sys
import json
import shutil
import time

LANG_FOLDER_MAP: dict[str, str] = {
    "en":    "en",
    "ja":    "ja",
    "zh":    "zh_cn",
    "zh_tw": "zh_tw",
    "ko":    "ko",
}


def _templates_dir() -> str:
    """Return the directory that directly contains en/, ja/, zh_cn/ etc.

    Dev:     <project>/worklogger/templates/  (this file's directory)
    Frozen:  _MEIPASS/templates/
    """
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        candidate = os.path.join(base, "templates")
        if os.path.isdir(candidate):
            return candidate
        return base
    else:
        # __file__ is <project>/worklogger/templates/__init__.py
        return os.path.dirname(os.path.abspath(__file__))


def _custom_dir() -> str:
    """Custom templates always live in a user-writable location.

    Frozen (exe):  next to the .exe  →  <exe_dir>/templates/custom/
    Dev:           project root       →  <project>/worklogger/templates/custom/
    """
    if getattr(sys, "frozen", False):
        # _MEIPASS is read-only, so custom templates must live beside the app.
        user_base = os.path.dirname(sys.executable)
    else:
        # Go up from templates/__init__.py to the worklogger package root.
        user_base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(user_base, "templates", "custom")
    os.makedirs(path, exist_ok=True)
    _seed_packaged_custom_templates(path)
    return path


def _bundled_custom_dir() -> str:
    """Return the bundled custom-template seed directory if it exists."""
    path = os.path.join(_templates_dir(), "custom")
    return path if os.path.isdir(path) else ""


def _seed_packaged_custom_templates(target_dir: str) -> None:
    """Copy packaged sample templates into the writable custom directory."""
    source_dir = _bundled_custom_dir()
    if not source_dir or os.path.abspath(source_dir) == os.path.abspath(target_dir):
        return
    try:
        for fname in os.listdir(source_dir):
            if not fname.lower().endswith(".json"):
                continue
            src = os.path.join(source_dir, fname)
            dst = os.path.join(target_dir, fname)
            if not os.path.isfile(src) or os.path.exists(dst):
                continue
            shutil.copyfile(src, dst)
    except Exception:
        pass


# Public alias used by dialogs.py.
CUSTOM_DIR = _custom_dir()

def get_template(lang: str, type_key: str) -> str:
    """Load the default built-in template for *lang* / *type_key*.
    Falls back to English if the lang-specific file is missing or empty.
    """
    tdir   = _templates_dir()
    folder = LANG_FOLDER_MAP.get(lang, "en")
    path   = os.path.join(tdir, folder, type_key, "default.md")
    if os.path.isfile(path):
        content = _read(path)
        if content:
            return content
    # Content loading can still fall back to English.
    en_path = os.path.join(tdir, "en", type_key, "default.md")
    if os.path.isfile(en_path):
        return _read(en_path)
    return ""


def list_builtin_template_types(lang: str) -> list[str]:
    """Return built-in template type keys found under the language folder.

    Types are discovered only from `<lang>/<type_key>/default.md`.
    This controls what appears in the built-in picker. Content loading still
    falls back to English inside `get_template`, but English-only template
    types should not appear when another language is selected.
    """
    tdir = _templates_dir()
    folder = LANG_FOLDER_MAP.get(lang, "en")
    found: set[str] = set()
    base_dir = os.path.join(tdir, folder)
    if not os.path.isdir(base_dir):
        return []
    try:
        entries = sorted(os.listdir(base_dir))
    except Exception:
        return []
    for entry in entries:
        path = os.path.join(base_dir, entry, "default.md")
        if os.path.isfile(path):
            found.add(entry)
    return sorted(found)


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""

def list_custom_templates(type_key: str | None = None) -> list[dict]:
    cdir = _custom_dir()
    result: list[dict] = []
    try:
        filenames = sorted(os.listdir(cdir))
    except FileNotFoundError:
        return []
    for fname in filenames:
        if not fname.endswith(".json"):
            continue
        try:
            raw  = _read(os.path.join(cdir, fname))
            data = json.loads(raw)
            if type_key is None or data.get("type") == type_key:
                data["filename"] = fname
                result.append(data)
        except Exception:
            pass
    return result


def save_custom_template(name: str, type_key: str, content: str) -> str:
    cdir  = _custom_dir()
    ts    = int(time.time() * 1000)
    safe  = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    fname = f"{safe}_{ts}.json"
    data  = {"name": name, "type": type_key, "content": content, "created": ts}
    with open(os.path.join(cdir, fname), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return fname


def get_custom_template_content(filename: str) -> str:
    try:
        raw  = _read(os.path.join(_custom_dir(), filename))
        data = json.loads(raw)
        return data.get("content", "")
    except Exception:
        return ""


def delete_custom_template(filename: str) -> None:
    path = os.path.join(_custom_dir(), filename)
    if os.path.isfile(path):
        os.remove(path)
