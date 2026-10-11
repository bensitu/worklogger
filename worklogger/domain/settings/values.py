"""Stored preference decoding shared by presentation and runtime adapters."""


def setting_bool(value: object, default: bool = False) -> bool:
    return default if value is None else str(value).strip().lower() in {"1", "true", "yes", "on"}


def setting_text(value: object, default: str = "") -> str:
    return str(value if value is not None else default).strip()
