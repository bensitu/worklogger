"""Structured serialization for SQLite report source references."""

from dataclasses import asdict, fields
import json
import math
from worklogger.domain.reporting.models import ReportProvenance, ReportSource


def encode_provenance(value):
    text = json.dumps(asdict(value), ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("report_content_too_long")
    return text


def decode_provenance(text):
    try:
        value = json.loads(text or "{}")
        if not isinstance(value, dict) or not isinstance(value.get("sources", []), list):
            raise ValueError("stored_records_invalid")
        sources = []
        for source in value.get("sources", []):
            if not isinstance(source, dict):
                raise ValueError("stored_records_invalid")
            decoded = ReportSource(**{field.name: source[field.name] for field in fields(ReportSource) if field.name in source})
            if (any(not isinstance(item, str) for item in (decoded.kind, decoded.identifier, decoded.digest))
                    or decoded.revision is not None and type(decoded.revision) is not int):
                raise ValueError("stored_records_invalid")
            sources.append(decoded)
        value["sources"] = tuple(sources)
        decoded = ReportProvenance(**{field.name: value[field.name] for field in fields(ReportProvenance) if field.name in value})
        if (any(not isinstance(item, str) for item in (decoded.generated_at, decoded.language, decoded.template_digest))
                or type(decoded.standard_hours) not in (int, float) or not math.isfinite(decoded.standard_hours)):
            raise ValueError("stored_records_invalid")
        return decoded
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("stored_records_invalid") from None
