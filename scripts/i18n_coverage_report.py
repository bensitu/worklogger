from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "worklogger"
LOCALES = SRC / "locales"
OUT = ROOT / "tests" / "_artifacts" / "i18n_coverage_report.json"
LANGS = ["ja_JP", "ko_KR", "zh_TW"]

# Ignore technical/brand tokens that are intentionally stable across locales.
IGNORE_EXACT = {
    "AI",
    "GitHub",
    "HH:MM",
    "OK",
    "CTO",
    "PTO",
    "WFH",
    "h",
    "key",
    "gpt-4o-mini | claude-haiku-4-5-20251001",
    "https://api.openai.com/v1 | https://api.anthropic.com",
    "sk-… / sk-ant-…",
    "{0:.0f} / {1:.0f} MB",
}
ALPHA = re.compile(r"[A-Za-z]")


def _parse_po(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
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
        msgstr = ""
        if i < len(lines) and lines[i].strip().startswith("msgstr "):
            msgstr = ast.literal_eval(lines[i].strip()[7:].strip())
            i += 1
            while i < len(lines) and lines[i].strip().startswith('"'):
                msgstr += ast.literal_eval(lines[i].strip())
                i += 1
        entries[msgid] = msgstr
    return entries


def _load_msg_defaults() -> dict[str, str]:
    i18n_py = SRC / "utils" / "i18n.py"
    tree = ast.parse(i18n_py.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "MSG_DEFAULTS" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        out: dict[str, str] = {}
        for k, v in zip(node.value.keys, node.value.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Constant) and isinstance(v.value, str):
                out[k.value] = v.value
        return out
    return {}


def _module_name(path: Path) -> str:
    rel = path.relative_to(SRC).parts
    if not rel:
        return "root"
    if rel[0] == "ui":
        return "ui/" + (rel[1] if len(rel) > 1 else "root")
    return rel[0]


def _collect_source_msgids() -> dict[str, set[str]]:
    msg_defaults = _load_msg_defaults()
    by_module: dict[str, set[str]] = defaultdict(set)

    for py in SRC.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        mod = _module_name(py)
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else None
            if name in {"_", "gettext"}:
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    by_module[mod].add(node.args[0].value)
            elif name == "ngettext":
                for idx in (0, 1):
                    if len(node.args) > idx and isinstance(node.args[idx], ast.Constant) and isinstance(node.args[idx].value, str):
                        by_module[mod].add(node.args[idx].value)
            elif name == "msg":
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                    by_module[mod].add(node.args[1].value)
                elif node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    fallback = msg_defaults.get(node.args[0].value)
                    if fallback:
                        by_module[mod].add(fallback)
    return by_module


def _is_translatable(msgid: str) -> bool:
    if not msgid:
        return False
    if msgid in IGNORE_EXACT:
        return False
    return bool(ALPHA.search(msgid))


def build_report() -> dict:
    source = _collect_source_msgids()
    result: dict[str, dict] = {"per_language": {}}

    for lang in LANGS:
        po_path = LOCALES / lang / "LC_MESSAGES" / "messages.po"
        po = _parse_po(po_path)
        per_module: dict[str, dict] = {}
        total_count = 0
        translated_count = 0
        over_10: list[str] = []

        for mod, msgids in sorted(source.items()):
            scoped = sorted([m for m in msgids if _is_translatable(m)])
            if not scoped:
                continue
            t = 0
            for mid in scoped:
                msgstr = po.get(mid, "")
                if msgstr and msgstr != mid:
                    t += 1
            total = len(scoped)
            missing = total - t
            missing_rate = missing / total
            per_module[mod] = {
                "translated": t,
                "total": total,
                "coverage_pct": round((t / total) * 100, 2),
                "missing_rate_pct": round(missing_rate * 100, 2),
            }
            total_count += total
            translated_count += t
            if missing_rate > 0.10:
                over_10.append(mod)

        overall = (translated_count / total_count) if total_count else 1.0
        result["per_language"][lang] = {
            "overall_coverage_pct": round(overall * 100, 2),
            "modules_over_10pct_missing": over_10,
            "modules": per_module,
        }
    return result


def main() -> int:
    report = build_report()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    for lang, data in report["per_language"].items():
        print(f"{lang}: {data['overall_coverage_pct']:.2f}%")
        if data["modules_over_10pct_missing"]:
            mods = ", ".join(data["modules_over_10pct_missing"])
            print(f"  >10% missing: {mods}")
        else:
            print("  >10% missing: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
