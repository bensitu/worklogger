from __future__ import annotations

import struct
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "worklogger" / "locales"
LANGS = ["en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR"]


def _parse_po(po_text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    msgid = None
    msgstr = None
    mode = None
    for raw in po_text.splitlines():
        line = raw.strip()
        if line.startswith("msgid "):
            msgid = line[7:-1]
            msgstr = None
            mode = "id"
        elif line.startswith("msgstr "):
            msgstr = line[8:-1]
            mode = "str"
            if msgid is not None:
                pairs[msgid] = msgstr
        elif line.startswith('"') and line.endswith('"'):
            frag = line[1:-1]
            if mode == "id" and msgid is not None:
                msgid += frag
            elif mode == "str" and msgid is not None:
                pairs[msgid] = pairs.get(msgid, "") + frag
    pairs.pop("", None)
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
