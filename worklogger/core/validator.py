"""Input validation and smart parsing."""

from datetime import datetime


def parse_time(raw: str) -> str | None:
    """
    Parse flexible time input and return 'HH:MM' or None.

    Examples
    --------
    '9'    → '09:00'
    '930'  → '09:30'
    '1630' → '16:30'
    '9:3'  → '09:03'
    '16:30'→ '16:30'
    """
    if not raw or not raw.strip():
        return None
    t = raw.strip().replace("：", ":").replace(".", ":")

    try:
        return datetime.strptime(t, "%H:%M").strftime("%H:%M")
    except ValueError:
        pass

    digits = t.replace(":", "").replace(" ", "")
    if digits.isdigit():
        n = len(digits)
        if n <= 2:
            h, m = int(digits), 0
        elif n == 3:
            h, m = int(digits[0]), int(digits[1:])
        else:
            h, m = int(digits[:-2]), int(digits[-2:])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return f"{h:02d}:{m:02d}"

    if ":" in t:
        parts = t.split(":", 1)
        try:
            h = int(parts[0])
            m = int(parts[1]) if parts[1] else 0
            if 0 <= h <= 23 and 0 <= m <= 59:
                return f"{h:02d}:{m:02d}"
        except ValueError:
            pass

    return None
