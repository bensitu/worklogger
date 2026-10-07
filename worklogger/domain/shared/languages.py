"""Supported language identifiers without a desktop-runtime dependency."""

SUPPORTED_LANGUAGES = ("en_US", "ja_JP", "ko_KR", "zh_CN", "zh_TW")
DEFAULT_LANGUAGE = "en_US"


def match_language(language: str | None) -> str | None:
    if not language:
        return None
    parts = language.strip().split(".", 1)[0].split("@", 1)[0].replace("-", "_").lower().split("_")
    prefix = parts[0]
    if prefix == "zh":
        if "hant" in parts:
            return "zh_TW"
        if "hans" in parts:
            return "zh_CN"
        return "zh_TW" if any(region in parts for region in ("tw", "hk", "mo")) else "zh_CN"
    return next((candidate for candidate in SUPPORTED_LANGUAGES if candidate.lower().startswith(prefix + "_")), None)


def normalize_language(language: str | None) -> str:
    return match_language(language) or DEFAULT_LANGUAGE
