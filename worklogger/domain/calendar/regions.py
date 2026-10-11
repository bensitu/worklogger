"""Holiday region validation against an explicitly supplied country catalog."""

from collections.abc import Mapping


def validate_holiday_region(value: str, supported: Mapping[str, tuple[str, ...]]) -> str:
    cleaned = str(value or "").strip().upper()
    if not cleaned:
        return ""
    country, separator, subdivision = cleaned.partition("/")
    if country not in supported or (separator and subdivision not in supported[country]):
        raise ValueError("holiday_region_invalid")
    return cleaned
