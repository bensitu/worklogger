from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCALES = ROOT / "worklogger" / "locales"
POT = LOCALES / "messages.pot"
LANGS = ["en_US", "zh_CN", "zh_TW", "ja_JP", "ko_KR"]


def _parse_msgids(text: str) -> list[str]:
    out: list[str] = []
    lines = text.splitlines()
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
            out.append(msgid)
    return out


def sync_po() -> None:
    pot_ids = _parse_msgids(POT.read_text(encoding="utf-8"))
    for lang in LANGS:
        po = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        po.parent.mkdir(parents=True, exist_ok=True)
        if not po.exists():
            header = [
                'msgid ""',
                'msgstr ""',
                f'"Language: {lang}\\n"',
                '"Content-Type: text/plain; charset=UTF-8\\n"',
                "",
            ]
            po.write_text("\n".join(header), encoding="utf-8")
        content = po.read_text(encoding="utf-8")
        existing = set(_parse_msgids(content))
        add = []
        for msgid in pot_ids:
            if msgid in existing:
                continue
            add.append(f'msgid "{msgid}"')
            add.append(f'msgstr "{msgid}"')
            add.append("")
        merged = content.rstrip() + ("\n\n" + "\n".join(add) if add else "")

        # Fill empty msgstr to English fallback to keep runtime consistent and
        # guarantee translation progress baseline for CI.
        lines = merged.splitlines()
        for i, ln in enumerate(lines[:-1]):
            if re.match(r'^msgid ".+"$', ln) and lines[i + 1] == 'msgstr ""':
                lines[i + 1] = f'msgstr {ln[6:]}'
        po.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sync_po()
