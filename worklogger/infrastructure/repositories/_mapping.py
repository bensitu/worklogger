"""SQLite row mapping helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone
import sqlite3
import logging
from collections.abc import Callable, Iterable
from typing import TypeVar

_T = TypeVar("_T")
_logger = logging.getLogger(__name__)


def map_rows(rows: Iterable[sqlite3.Row], mapper: Callable[[sqlite3.Row], _T]) -> tuple[_T, ...]:
    records = []
    invalid = 0
    for row in rows:
        try:
            records.append(mapper(row))
        except (TypeError, ValueError, OverflowError):
            invalid += 1
    if invalid:
        _logger.warning("Stored records could not be decoded: count=%d", invalid)
    return tuple(records)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_date(value: object) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                _logger.warning("Stored timestamp could not be decoded")
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def bool_from_row(row: sqlite3.Row, key: str) -> bool:
    return bool(int(row[key] or 0))
