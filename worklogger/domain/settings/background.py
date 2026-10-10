"""Account-owned background media and bounded rendering preferences."""

from dataclasses import dataclass, field
from typing import Protocol

MIN_BACKGROUND_LONG_EDGE = 1280
MIN_BACKGROUND_SHORT_EDGE = 720
MAX_BACKGROUND_BYTES = 20 * 1024 * 1024
MAX_BACKGROUND_FRAME_PIXELS = 16_000_000
MAX_BACKGROUND_TOTAL_PIXELS = 128_000_000
MAX_BACKGROUND_FRAMES = 300
BACKGROUND_FORMATS = ("png", "jpeg", "webp", "gif")


def validate_opacity(value: int) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("background_opacity_invalid")
    return value


@dataclass(frozen=True)
class BackgroundImage:
    data: bytes = field(repr=False)
    format: str
    width: int
    height: int
    frames: int = 1

    def __post_init__(self):
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("background_image_invalid")
        if len(self.data) > MAX_BACKGROUND_BYTES:
            raise ValueError("background_image_too_large")
        if self.format not in BACKGROUND_FORMATS:
            raise ValueError("background_image_invalid")
        if any(type(value) is not int or value <= 0 for value in (self.width, self.height, self.frames)):
            raise ValueError("background_image_invalid")
        if max(self.width, self.height) < MIN_BACKGROUND_LONG_EDGE or min(self.width, self.height) < MIN_BACKGROUND_SHORT_EDGE:
            raise ValueError("background_image_resolution_low")
        if self.width * self.height > MAX_BACKGROUND_FRAME_PIXELS:
            raise ValueError("background_image_too_large")
        if self.frames > MAX_BACKGROUND_FRAMES or self.width * self.height * self.frames > MAX_BACKGROUND_TOTAL_PIXELS:
            raise ValueError("background_animation_too_large")

    @property
    def animated(self) -> bool:
        return self.frames > 1


@dataclass(frozen=True)
class BackgroundState:
    image: BackgroundImage | None = field(default=None, repr=False)
    enabled: bool = False
    opacity: int = 50

    def __post_init__(self):
        validate_opacity(self.opacity)
        if type(self.enabled) is not bool:
            raise ValueError("background_enabled_invalid")


class BackgroundRepository(Protocol):
    def load(self, user_id: int) -> BackgroundState: ...
    def replace_image(self, user_id: int, image: BackgroundImage) -> BackgroundState: ...
    def set_options(self, user_id: int, *, enabled: bool, opacity: int) -> BackgroundState: ...
    def clear(self, user_id: int) -> BackgroundState: ...
