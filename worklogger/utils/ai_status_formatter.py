from __future__ import annotations
import json


def _decode_status_payload(msg: str) -> dict | None:
    candidate = msg
    for _ in range(2):
        if not isinstance(candidate, str):
            return None
        text = candidate.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str):
            candidate = parsed
            continue
        return None
    return None


def parse_status(msg: str) -> tuple[str | None, dict]:
    payload = _decode_status_payload(msg)
    if isinstance(payload, dict) and "key" in payload:
        kw = dict(payload)
        key = str(kw.pop("key"))
        return key, kw

    mapping = {
        "Preparing AI request...": "ai_status_start",
        "Preparing request for model {model}...": "ai_status_build",
        "Connecting to model {model}...": "ai_status_connect",
        "Waiting for AI response...": "ai_status_wait",
        "Processing AI response...": "ai_status_parse",
        "Done.": "ai_status_done",
        "Error: ": "ai_status_error",
    }
    for en, key in mapping.items():
        if "{model}" in en:
            prefix = en.split("{model}")[0]
            if msg.startswith(prefix):
                model_part = msg[len(prefix):].split("...")[0].strip()
                return key, {"model": model_part}
        elif msg.startswith(en):
            return key, {}
    return None, {"raw": msg}


def render_status_text(msg: str, i18n_map: dict) -> str:
    key, kw = parse_status(msg)
    if not key:
        return kw.get("raw", msg)
    template = i18n_map.get(key, key)
    try:
        return template.format(**kw)
    except Exception:
        return template
