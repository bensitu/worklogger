"""Recurring weekly work plans with optional excluded calendar dates."""

from dataclasses import dataclass
from datetime import date
from collections.abc import Iterable
import json


@dataclass(frozen=True)
class WorkSchedule:
    mode: str = "full_month"
    days: tuple[float, ...] = (1, 1, 1, 1, 1, 1, 1)

    def __post_init__(self):
        if (not isinstance(self.mode, str) or self.mode not in {"full_month", "one_day_off", "two_days_off", "two_and_a_half_days_off", "custom"}
                or not isinstance(self.days, tuple) or len(self.days) != 7
                or any(type(value) not in (int, float) or value not in (0, 0.5, 1) for value in self.days)):
            raise ValueError("work_schedule_invalid")
        expected = {"full_month": (0, 0), "one_day_off": (1, 0), "two_days_off": (2, 0), "two_and_a_half_days_off": (2, 1)}
        if self.mode in expected and (self.days.count(0), self.days.count(0.5)) != expected[self.mode]:
            raise ValueError("work_schedule_invalid")

    @classmethod
    def preset(cls, mode: str):
        days = {"full_month": (1, 1, 1, 1, 1, 1, 1), "one_day_off": (1, 1, 1, 1, 1, 1, 0),
                "two_days_off": (1, 1, 1, 1, 1, 0, 0), "two_and_a_half_days_off": (1, 1, 1, 1, 0.5, 0, 0),
                "custom": (1, 1, 1, 1, 1, 0, 0)}
        return cls(mode, days[mode])

    @classmethod
    def decode(cls, value: str):
        try:
            if not isinstance(value, str) or len(value) > 512:
                raise ValueError("work_schedule_invalid")
            data = json.loads(value)
            if not isinstance(data, dict) or set(data) != {"mode", "days"} or not isinstance(data["days"], list):
                raise ValueError("work_schedule_invalid")
            return cls(data["mode"], tuple(data["days"]))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("work_schedule_invalid") from exc

    @classmethod
    def from_setting(cls, value: str | None):
        try:
            return cls.decode(value)
        except ValueError:
            return cls()

    def encode(self) -> str:
        return json.dumps({"mode": self.mode, "days": self.days}, separators=(",", ":"))

    def planned_days(self, start: date, end: date, *, holidays: Iterable[date] = ()) -> float:
        if end < start:
            return 0.0
        weeks, remaining = divmod((end - start).days + 1, 7)
        scheduled = weeks * sum(self.days) + sum(self.days[(start.weekday() + offset) % 7] for offset in range(remaining))
        return scheduled - sum(self.days[day.weekday()] for day in set(holidays) if start <= day <= end)
