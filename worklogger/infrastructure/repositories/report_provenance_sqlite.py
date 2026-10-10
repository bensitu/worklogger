"""Structured serialization for SQLite report source references."""

from dataclasses import asdict
import json
from worklogger.domain.reporting.models import ReportProvenance, ReportSource


def encode_provenance(value):
    text = json.dumps(asdict(value), ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("report_content_too_long")
    return text


def decode_provenance(text):
    value = json.loads(text or "{}")
    value["sources"] = tuple(ReportSource(**source) for source in value.get("sources", ()))
    return ReportProvenance(**value)
