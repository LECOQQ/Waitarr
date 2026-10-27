"""Parse and format the two units a person writes in a config file:
durations and transfer rates."""

from __future__ import annotations

import math
import re
from datetime import timedelta

__all__ = [
    "format_duration",
    "format_rate",
    "parse_duration",
    "parse_rate",
]

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|h|m|s)")
_DURATION_SECONDS = {"h": 3600.0, "m": 60.0, "s": 1.0, "ms": 0.001}

_RATE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*((?:[kmg]i?)?b)?\s*(?:/s)?\s*$", re.I
)
_RATE_FACTORS = {
    None: 1,
    "b": 1,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "kb": 1000,
    "mb": 1000**2,
    "gb": 1000**3,
}


def parse_duration(value: str | int | float) -> timedelta:
    """Accept seconds as a number, or "90s", "3m", "1h30m", "250ms"."""
    if isinstance(value, bool):
        raise ValueError(f"not a duration: {value!r}")
    if isinstance(value, int | float):
        if not math.isfinite(value):
            raise ValueError(f"a duration must be finite: {value!r}")
        if value < 0:
            raise ValueError(f"a duration cannot be negative: {value!r}")
        return timedelta(seconds=value)
    text = value.strip().lower().replace(" ", "")
    if text.isdigit():
        return timedelta(seconds=int(text))
    position = 0
    seconds = 0.0
    for match in _DURATION_PART.finditer(text):
        if match.start() != position:
            break
        seconds += float(match.group(1)) * _DURATION_SECONDS[match.group(2)]
        position = match.end()
    if position == 0 or position != len(text):
        raise ValueError(
            f"not a duration: {value!r} (write e.g. '15s', '3m', '1h30m')"
        )
    return timedelta(seconds=seconds)


def parse_rate(value: str | int) -> int:
    """Return bytes per second from "1KiB", "512 KiB/s", "2MiB" or bytes."""
    if isinstance(value, bool):
        raise ValueError(f"not a rate: {value!r}")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"a rate cannot be negative: {value!r}")
        return value
    match = _RATE.match(value)
    if match is None:
        raise ValueError(
            f"not a rate: {value!r} (write e.g. '1KiB', '512KiB', '2MiB')"
        )
    unit = match.group(2).lower() if match.group(2) else None
    return int(float(match.group(1)) * _RATE_FACTORS[unit])


def format_rate(bytes_per_second: int) -> str:
    if bytes_per_second == 0:
        return "unlimited"
    for factor, unit in ((1024**3, "GiB"), (1024**2, "MiB"), (1024, "KiB")):
        if bytes_per_second >= factor:
            amount = bytes_per_second / factor
            text = f"{amount:.1f}".removesuffix(".0")
            return f"{text} {unit}/s"
    return f"{bytes_per_second} B/s"


def format_duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    parts = [
        f"{hours}h" if hours else "",
        f"{minutes}m" if minutes else "",
        f"{seconds}s" if seconds or total == 0 else "",
    ]
    return "".join(parts)
