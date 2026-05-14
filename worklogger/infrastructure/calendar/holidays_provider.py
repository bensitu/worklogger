"""Public holiday provider backed by the optional holidays package."""

from __future__ import annotations

from datetime import date, datetime
from importlib import import_module
from typing import Any

from worklogger.config.constants import TZ_COUNTRY
from worklogger.domain.calendar.models import Holiday


class PythonHolidaysProvider:
    def __init__(self, holidays_module: Any | None = None) -> None:
        self._holidays_module = holidays_module

    def list_for_range(
        self,
        country: str,
        start_day: date,
        end_day: date,
    ) -> tuple[Holiday, ...]:
        if end_day < start_day:
            return ()
        module = self._holidays_module or _load_holidays_module()
        if module is None:
            return ()
        years = tuple(range(start_day.year, end_day.year + 1))
        try:
            raw_holidays = module.country_holidays(country, years=years)
        except Exception:
            return ()
        holidays: list[Holiday] = []
        for day_value, name in raw_holidays.items():
            day = _coerce_date(day_value)
            if day is None or day < start_day or day > end_day:
                continue
            holidays.append(Holiday(day=day, name=str(name)))
        return tuple(sorted(holidays, key=lambda holiday: holiday.day))


def detect_country(default: str = "US") -> str:
    try:
        tzlocal = import_module("tzlocal")
        timezone_name = str(tzlocal.get_localzone())
    except Exception:
        timezone_name = ""
    return TZ_COUNTRY.get(timezone_name, default)


def _load_holidays_module() -> Any | None:
    try:
        return import_module("holidays")
    except Exception:
        return None


def _coerce_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
