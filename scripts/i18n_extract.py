from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "worklogger"
OUT = SRC / "locales" / "messages.pot"
I18N_RUNTIME = SRC / "utils" / "i18n.py"


def _iter_py_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


def _load_msg_defaults() -> dict[str, str]:
    try:
        tree = ast.parse(I18N_RUNTIME.read_text(encoding="utf-8"))
    except Exception:
        return {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "MSG_DEFAULTS" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            return {}
        out: dict[str, str] = {}
        for k, v in zip(node.value.keys, node.value.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Constant) and isinstance(v.value, str):
                out[k.value] = v.value
        return out
    return {}


def _collect_strings(text: str, msg_defaults: dict[str, str]) -> set[str]:
    out: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else None
        if name in {"_", "gettext"}:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                out.add(node.args[0].value)
        elif name == "ngettext":
            for idx in (0, 1):
                if len(node.args) > idx and isinstance(node.args[idx], ast.Constant) and isinstance(node.args[idx].value, str):
                    out.add(node.args[idx].value)
        elif name == "msg":
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
                out.add(node.args[1].value)
            elif node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                fallback = msg_defaults.get(node.args[0].value)
                if fallback:
                    out.add(fallback)
    return out


def _esc_po(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def build_pot() -> None:
    msg_defaults = _load_msg_defaults()
    keys: set[str] = set()
    for fp in _iter_py_files():
        keys |= _collect_strings(fp.read_text(encoding="utf-8"), msg_defaults)
    lines = [
        'msgid ""',
        'msgstr ""',
        '"Project-Id-Version: WorkLogger\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        "",
    ]
    for key in sorted(keys):
        lines.append(f'msgid "{_esc_po(key)}"')
        lines.append('msgstr ""')
        lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    build_pot()
