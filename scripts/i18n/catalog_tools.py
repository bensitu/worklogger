"""Shared gettext catalog helpers for WorkLogger scripts."""

from __future__ import annotations

import ast
import json
import struct
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / "worklogger"
LOCALES_ROOT = SOURCE_ROOT / "locales"
POT_PATH = LOCALES_ROOT / "messages.pot"
LANGUAGES = ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW")


def _decode_po_string(line: str) -> str:
    return ast.literal_eval(line.strip())


def read_po_entries(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    current_id: str | None = None
    current_str = ""
    current_field: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            if current_id is not None:
                entries[current_id] = current_str
            current_id = _decode_po_string(line[6:].strip())
            current_str = ""
            current_field = "msgid"
        elif line.startswith("msgstr "):
            current_str = _decode_po_string(line[7:].strip())
            current_field = "msgstr"
        elif line.startswith('"') and current_field == "msgid" and current_id is not None:
            current_id += _decode_po_string(line)
        elif line.startswith('"') and current_field == "msgstr":
            current_str += _decode_po_string(line)
    if current_id is not None:
        entries[current_id] = current_str
    return entries


def read_po_msgids(path: Path) -> set[str]:
    return {msgid for msgid in read_po_entries(path) if msgid}


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract_source_messages(source_root: Path = SOURCE_ROOT) -> set[str]:
    messages: set[str] = set()
    for path in sorted(source_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "_":
                if node.args:
                    message = _constant_string(node.args[0])
                    if message:
                        messages.add(message)
            elif isinstance(node.func, ast.Name) and node.func.id == "ngettext":
                for arg in node.args[:2]:
                    message = _constant_string(arg)
                    if message:
                        messages.add(message)
    return messages


def _po_quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def write_pot(messages: set[str], path: Path = POT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: WorkLogger 4.0.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        '"MIME-Version: 1.0\\n"',
        "",
    ]
    for message in sorted(messages):
        lines.append(f"msgid {_po_quote(message)}")
        lines.append('msgstr ""')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_po(language: str, messages: set[str], locales_root: Path = LOCALES_ROOT) -> Path:
    path = locales_root / language / "LC_MESSAGES" / "messages.po"
    existing = read_po_entries(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: WorkLogger 4.0.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        f'"Language: {language}\\n"',
        '"MIME-Version: 1.0\\n"',
        "",
    ]
    for message in sorted(messages):
        translation = message if language == "en_US" else existing.get(message, "")
        lines.append(f"msgid {_po_quote(message)}")
        lines.append(f"msgstr {_po_quote(translation)}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def compile_po_to_mo(po_path: Path, mo_path: Path | None = None) -> Path:
    mo_path = mo_path or po_path.with_suffix(".mo")
    entries = read_po_entries(po_path)
    keys = sorted(entries)
    ids = b""
    strings = b""
    id_offsets: list[tuple[int, int]] = []
    string_offsets: list[tuple[int, int]] = []
    for key in keys:
        raw_key = key.encode("utf-8")
        id_offsets.append((len(raw_key), len(ids)))
        ids += raw_key + b"\0"
        raw_value = entries[key].encode("utf-8")
        string_offsets.append((len(raw_value), len(strings)))
        strings += raw_value + b"\0"

    count = len(keys)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    ids_offset = value_table_offset + count * 8
    strings_offset = ids_offset + len(ids)

    output = [
        struct.pack("Iiiiiii", 0x950412DE, 0, count, key_table_offset, value_table_offset, 0, 0)
    ]
    output.extend(
        struct.pack("ii", length, ids_offset + offset)
        for length, offset in id_offsets
    )
    output.extend(
        struct.pack("ii", length, strings_offset + offset)
        for length, offset in string_offsets
    )
    output.append(ids)
    output.append(strings)

    mo_path.parent.mkdir(parents=True, exist_ok=True)
    mo_path.write_bytes(b"".join(output))
    return mo_path


def locale_po_paths(locales_root: Path = LOCALES_ROOT) -> list[Path]:
    return [
        locales_root / language / "LC_MESSAGES" / "messages.po"
        for language in LANGUAGES
    ]

