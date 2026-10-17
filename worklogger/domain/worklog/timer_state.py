"""Automatic recording state and compatible persisted representations."""

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime

from worklogger.config.constants import MAX_SHIFT_HOURS
from worklogger.domain.projects.models import WorkContext
from worklogger.domain.worklog.content import require_entry_content
from worklogger.domain.worklog.models import CustomEntryType, EntryType, EntryCategory, WorkMode
from worklogger.domain.worklog.rules import decode_entry_type, timestamp_span_hours


@dataclass(frozen=True)
class EntryTimer:
    capture_id: str
    started_at: datetime
    entry_type: EntryType | CustomEntryType
    content: str = ""
    break_until: datetime | None = None
    resume_type: EntryType | CustomEntryType | None = None
    resume_content: str = ""
    legacy_break_hours: float = 0.0
    pending_end: datetime | None = None
    context: WorkContext = WorkContext()
    work_mode: WorkMode | None = None


def encode_timer(timer: EntryTimer | None) -> str | None:
    if timer is None:
        return None
    data = asdict(timer)
    for key in ("entry_type", "resume_type"):
        definition = getattr(timer, key)
        data[key] = definition.value if definition is not None else None
        if isinstance(definition, CustomEntryType):
            data[key + "_label"] = definition.label
            data[key + "_category"] = definition.category
    for key in ("started_at", "break_until", "pending_end"):
        data[key] = data[key].isoformat() if data[key] else None
    return json.dumps(data, allow_nan=False, ensure_ascii=False)


def decode_timer(raw: str) -> EntryTimer:
    data = timer_payload(raw)
    # Released and previously persisted timers use the original classification key.
    for suffix in ("", "_label", "_category"):
        old_key = "work_type" + suffix
        if old_key in data:
            if "entry_type" + suffix in data:
                raise ValueError("auto_record_restore_failed")
            data["entry_type" + suffix] = data.pop(old_key)
    data["context"] = WorkContext(**data.get("context", {}))
    for key in ("started_at", "break_until", "pending_end"):
        data[key] = datetime.fromisoformat(data[key]) if data.get(key) else None
    for key in ("entry_type", "resume_type"):
        label = data.pop(key + "_label", "")
        category = data.pop(key + "_category", "")
        data[key] = decode_entry_type(data[key], label=label, category=category, strict=True) if data.get(key) else None
    if "work_mode" not in data:
        data["work_mode"] = {EntryType.REMOTE: WorkMode.REMOTE, EntryType.BUSINESS_TRIP: WorkMode.BUSINESS_TRIP}.get(data["entry_type"])
    elif data["work_mode"] is not None:
        data["work_mode"] = WorkMode(data["work_mode"])
    timer = EntryTimer(**data)
    if timer.entry_type.category != EntryCategory.WORK and (timer.work_mode is not None or timer.context != WorkContext()):
        raise ValueError("auto_record_restore_failed")
    if (not math.isfinite(timer.legacy_break_hours) or not 0 <= timer.legacy_break_hours <= MAX_SHIFT_HOURS
            or bool(timer.break_until) != bool(timer.resume_type)):
        raise ValueError("auto_record_restore_failed")
    require_entry_content(timer.content)
    require_entry_content(timer.resume_content)
    if timer.break_until:
        if not 0 < timestamp_span_hours(timer.started_at, timer.break_until) <= 4:
            raise ValueError("auto_record_restore_failed")
        if timer.entry_type != EntryType.BREAK or timer.resume_type == EntryType.BREAK or timer.pending_end:
            raise ValueError("auto_record_restore_failed")
    return timer


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
