"""Validation for user-controlled presentation names."""

import unicodedata


def normalize_display_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("display_name_invalid")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value):
        raise ValueError("display_name_invalid")
    cleaned = value.strip()
    if len(cleaned) > 80:
        raise ValueError("display_name_too_long")
    return cleaned
