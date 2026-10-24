"""Finite axis intervals shared by screen and document charts."""

from math import floor, isfinite, log10


def chart_tick_step(maximum: float) -> float:
    if not isfinite(maximum):
        maximum = 1.0
    raw = max(1.0, maximum) / 4
    magnitude = 10 ** floor(log10(raw))
    return next(step * magnitude for step in (1, 2, 2.5, 5, 10) if step * magnitude >= raw)
