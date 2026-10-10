"""Runtime context preferences independent of declared model capacity."""

import math

DEFAULT_RUNTIME_CONTEXT_TOKENS = 8192
MIN_RUNTIME_CONTEXT_TOKENS = 512
MAX_RUNTIME_CONTEXT_TOKENS = 2_147_483_647


def normalize_runtime_context(value) -> int:
    try:
        number = float(value)
        if isinstance(value, bool) or not math.isfinite(number) or not number.is_integer():
            raise ValueError
        tokens = int(number)
        if not MIN_RUNTIME_CONTEXT_TOKENS <= tokens <= MAX_RUNTIME_CONTEXT_TOKENS:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise ValueError("local_runtime_context_invalid") from None
    return tokens


def runtime_context_preference(value) -> int:
    try:
        return normalize_runtime_context(value)
    except ValueError:
        return DEFAULT_RUNTIME_CONTEXT_TOKENS


def effective_runtime_context(requested: int, model_limit: int) -> int:
    if model_limit < MIN_RUNTIME_CONTEXT_TOKENS:
        raise ValueError("local_model_context_limit_invalid")
    return min(normalize_runtime_context(requested), model_limit)
