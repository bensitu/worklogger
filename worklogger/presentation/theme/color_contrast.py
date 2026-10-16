"""Shared sRGB color measurement, scaling, and blending."""

from functools import lru_cache


@lru_cache(maxsize=256)
def relative_luminance(color: str) -> float:
    channels = (int(color[index:index + 2], 16) / 255 for index in (1, 3, 5))
    return sum(weight * (channel / 12.92 if channel <= 0.04045
                        else ((channel + 0.055) / 1.055) ** 2.4)
               for weight, channel in zip((0.2126, 0.7152, 0.0722), channels))


def contrast_ratio(first: str, second: str) -> float:
    low, high = sorted((relative_luminance(first), relative_luminance(second)))
    return (high + 0.05) / (low + 0.05)


def mix_colors(first: str, second: str, amount: float) -> str:
    amount = max(0.0, min(1.0, amount))
    return "#" + "".join(f"{round(start + (end - start) * amount):02x}"
        for start, end in ((int(first[index:index + 2], 16), int(second[index:index + 2], 16))
                           for index in (1, 3, 5)))


def scale_color(color: str, factor: float) -> str:
    return "#" + "".join(f"{max(0, min(255, round(int(color[index:index + 2], 16) * factor))):02x}"
                         for index in (1, 3, 5))


def contrasting_foreground(background: str) -> str:
    return max(("#000000", "#ffffff"), key=lambda color: contrast_ratio(color, background))
