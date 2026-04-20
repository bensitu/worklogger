from __future__ import annotations

import ast
import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "worklogger" / "locales"
LANGS = ["en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR"]


def _parse_po(po_text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    lines = po_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line.startswith("msgid "):
            i += 1
            continue

        msgid = ast.literal_eval(line[6:].strip())
        i += 1
        while i < len(lines) and lines[i].strip().startswith('"'):
            msgid += ast.literal_eval(lines[i].strip())
            i += 1

        msgstr = ""
        if i < len(lines) and lines[i].strip().startswith("msgstr "):
            msgstr = ast.literal_eval(lines[i].strip()[7:].strip())
            i += 1
            while i < len(lines) and lines[i].strip().startswith('"'):
                msgstr += ast.literal_eval(lines[i].strip())
                i += 1

        pairs[msgid] = msgstr

    header = pairs.get("", "")
    if not header:
        pairs[""] = "Content-Type: text/plain; charset=UTF-8\\n"
    elif "charset=" not in header.lower():
        suffix = "" if header.endswith("\n") else "\n"
        pairs[""] = header + suffix + "Content-Type: text/plain; charset=UTF-8\\n"
    return pairs


def _write_mo(entries: dict[str, str], out_file: Path) -> None:
    ids = sorted(entries.keys())
    strs = [entries[k] for k in ids]
    ids_b = [s.encode("utf-8") for s in ids]
    strs_b = [s.encode("utf-8") for s in strs]
    n = len(ids)
    keystart = 7 * 4
    valuestart = keystart + n * 8
    id_offset = valuestart + n * 8

    koffsets = []
    off = id_offset
    for b in ids_b:
        koffsets.append((len(b), off))
        off += len(b) + 1
    voff = off
    voffsets = []
    for b in strs_b:
        voffsets.append((len(b), voff))
        voff += len(b) + 1

    out = bytearray()
    out += struct.pack("Iiiiiii", 0x950412DE, 0, n, keystart, valuestart, 0, 0)
    for ln, ofs in koffsets:
        out += struct.pack("ii", ln, ofs)
    for ln, ofs in voffsets:
        out += struct.pack("ii", ln, ofs)
    for b in ids_b:
        out += b + b"\0"
    for b in strs_b:
        out += b + b"\0"
    out_file.write_bytes(out)


def compile_all() -> None:
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        mo = LOCALES / lang / "LC_MESSAGES" / "messages.mo"
        if not po.exists():
            continue
        entries = _parse_po(po.read_text(encoding="utf-8"))
        _write_mo(entries, mo)


if __name__ == "__main__":
    compile_all()
