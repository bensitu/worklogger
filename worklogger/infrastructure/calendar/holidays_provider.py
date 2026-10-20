"""Public holiday provider backed by the optional holidays package."""

from __future__ import annotations

from datetime import date, datetime
from importlib import import_module
from importlib.resources import files
from functools import lru_cache
from typing import Any

from worklogger.config.constants import TZ_COUNTRY
from worklogger.domain.calendar.models import Holiday
from worklogger.domain.calendar.regions import validate_holiday_region as validate_region


class PythonHolidaysProvider:
    def __init__(self, holidays_module: Any | None = None) -> None:
        self._holidays_module = holidays_module

    def list_for_range(
        self,
        country: str,
        start_day: date,
        end_day: date,
        *,
        subdivision: str | None = None,
    ) -> tuple[Holiday, ...]:
        if end_day < start_day:
            return ()
        module = self._holidays_module or _load_holidays_module()
        if module is None:
            raise RuntimeError("holiday_provider_unavailable")
        years = tuple(range(start_day.year, end_day.year + 1))
        raw_holidays = _holiday_items(module, country, years, subdivision)
        holidays: list[Holiday] = []
        for day_value, name in raw_holidays:
            day = _coerce_date(day_value)
            if day is None or day < start_day or day > end_day:
                continue
            holidays.append(Holiday(day=day, name=str(name)))
        return tuple(sorted(holidays, key=lambda holiday: holiday.day))


@lru_cache(maxsize=64)
def _holiday_items(module, country, years, subdivision):
    options = {"years": years}
    if subdivision:
        options["subdiv"] = subdivision
    try:
        return tuple(module.country_holidays(country, **options).items())
    except (KeyError, ValueError, TypeError, NotImplementedError):
        raise ValueError("holiday_region_invalid") from None


@lru_cache(maxsize=1)
def _timezone_countries() -> dict[str, str]:
    mapping = dict(TZ_COUNTRY)
    for line in files("tzdata.zoneinfo").joinpath("zone.tab").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            country, _coordinates, zone, *_comment = line.split("\t")
            mapping[zone] = country
    return mapping


def supported_holiday_regions() -> dict[str, tuple[str, ...]]:
    module = _load_holidays_module()
    if module is None:
        return {}
    return _supported_holiday_regions(module)


@lru_cache(maxsize=1)
def _supported_holiday_regions(module) -> dict[str, tuple[str, ...]]:
    return {country: tuple(subdivisions) for country, subdivisions in module.list_supported_countries().items()
            if len(country) == 2}


def validate_holiday_region(value: str) -> str:
    return validate_region(value, supported_holiday_regions())


def detect_country(default: str = "") -> str:
    try:
        tzlocal = import_module("tzlocal")
        timezone_name = str(tzlocal.get_localzone())
    except Exception:
        timezone_name = ""
    try:
        return _timezone_countries().get(timezone_name, default)
    except (OSError, ImportError):
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
