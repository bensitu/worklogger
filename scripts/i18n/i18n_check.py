from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "worklogger" / "locales"
POT = LOCALES / "messages.pot"
LANGS = ["en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR"]


def _ids(path: Path) -> set[str]:
    out = set()
    lines = path.read_text(encoding="utf-8").splitlines()
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
        if msgid:
            out.add(msgid)
    return out


def _untranslated_ratio(po: Path) -> float:
    total = done = 0
    lines = po.read_text(encoding="utf-8").splitlines()
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
        if not msgid:
            continue
        total += 1
        msgstr = ""
        if i < len(lines) and lines[i].strip().startswith("msgstr "):
            msgstr = ast.literal_eval(lines[i].strip()[7:].strip())
            i += 1
            while i < len(lines) and lines[i].strip().startswith('"'):
                msgstr += ast.literal_eval(lines[i].strip())
                i += 1
        if msgstr:
            done += 1
    return (done / total) if total else 1.0


def main() -> int:
    if not POT.exists():
        print("FAIL: messages.pot missing")
        return 1
    pot_ids = _ids(POT)
    ok = True
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        mo = LOCALES / lang / "LC_MESSAGES" / "messages.mo"
        if not po.exists():
            print(f"FAIL: missing {po}")
            ok = False
            continue
        po_ids = _ids(po)
        if pot_ids - po_ids:
            print(f"FAIL: {lang} missing {len(pot_ids - po_ids)} keys")
            ok = False
        ratio = _untranslated_ratio(po)
        if ratio < 0.95:
            print(f"FAIL: {lang} translated ratio {ratio:.2%} < 95%")
            ok = False
        if not mo.exists() or mo.stat().st_mtime < po.stat().st_mtime:
            print(f"FAIL: {lang} .mo missing/outdated")
            ok = False
    if ok:
        print("OK: i18n checks passed")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
