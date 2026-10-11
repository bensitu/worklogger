"""Validate persisted timer headers before recovery or overlap checks."""

import json
from datetime import datetime


def timer_payload(raw: str) -> dict:
    try:
        if not isinstance(raw, str) or len(raw) > 128 * 1024:
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError
        capture = data["capture_id"]
        if not isinstance(capture, str) or not capture or len(capture) > 64:
            raise ValueError
        if not isinstance(data.get("context", {}), dict):
            raise TypeError
        for field in ("started_at", "break_until", "pending_end"):
            value = data.get(field)
            if value is None and field != "started_at":
                continue
            if not isinstance(value, str):
                raise TypeError
            moment = datetime.fromisoformat(value)
            if moment.tzinfo is None or moment.utcoffset() is None:
                raise ValueError
        return data
    except (KeyError, TypeError, ValueError, RecursionError) as exc:
        raise ValueError("auto_record_restore_failed") from exc
