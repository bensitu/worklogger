from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "worklogger" / "locales"
POT = LOCALES / "messages.pot"
LANGS = ["en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR"]


def _ids(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    out = set()
    for ln in text.splitlines():
        m = re.match(r'^msgid "(.*)"$', ln)
        if m and m.group(1):
            out.add(m.group(1))
    return out


def _untranslated_ratio(po: Path) -> float:
    text = po.read_text(encoding="utf-8")
    total = done = 0
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if re.match(r'^msgid ".+"$', ln):
            total += 1
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if re.match(r'^msgstr ".+"$', nxt):
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
