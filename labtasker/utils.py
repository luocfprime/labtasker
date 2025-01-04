import re
from datetime import datetime, timedelta, timezone
from typing import Union


def parse_timeout(timeout_str: str) -> int:
    """Convert timeout string to seconds.

    Supports formats:
    - Single unit: "1.5h", "30m", "60s"
    - Multiple units: "1h30m", "5m30s", "1h30m15s"
    - Full words: "1 hour", "30 minutes", "1 hour, 30 minutes"

    Args:
        timeout_str: Timeout string to parse

    Returns:
        Number of seconds (rounded to nearest integer)

    Raises:
        ValueError: If format is invalid
    """
    if not timeout_str or not isinstance(timeout_str, str):
        raise ValueError("Timeout must be a non-empty string")

    # Clean up input
    timeout_str = timeout_str.lower().strip()
    timeout_str = re.sub(
        r"[:,\s]+", "", timeout_str
    )  # Remove all spaces, commas, and colons

    # Handle pure numbers (assume seconds)
    if timeout_str.isdigit():
        return int(timeout_str)

    # Unit mappings
    unit_map = {
        "h": 3600,
        "hour": 3600,
        "hours": 3600,
        "m": 60,
        "min": 60,
        "minute": 60,
        "minutes": 60,
        "s": 1,
        "sec": 1,
        "second": 1,
        "seconds": 1,
    }

    total_seconds = 0

    # Match alternating number-unit pairs
    matches = re.findall(r"(\d+\.?\d*)([a-z]+)", timeout_str)
    if not matches or "".join(num + unit for num, unit in matches) != timeout_str:
        raise ValueError(f"Invalid timeout format: {timeout_str}")

    for value_str, unit in matches:
        try:
            value = float(value_str)
        except ValueError:
            raise ValueError(f"Invalid number: {value_str}")

        if unit not in unit_map:
            raise ValueError(f"Invalid unit: {unit}")

        total_seconds += value * unit_map[unit]

    return round(total_seconds)


def get_timeout_delta(timeout: Union[int, str]) -> timedelta:
    """Convert timeout to timedelta.

    Args:
        timeout: Either seconds (int) or timeout string

    Returns:
        timedelta object
    """
    if isinstance(timeout, (int, float)):
        if not isinstance(timeout, int):
            raise ValueError("Direct seconds must be an integer")
        return timedelta(seconds=timeout)

    if isinstance(timeout, str):
        seconds = parse_timeout(timeout)
        return timedelta(seconds=seconds)

    raise TypeError("Timeout must be an integer or string")


def get_current_time() -> datetime:
    """Get current UTC time. Centralized to make testing easier."""
    return datetime.now(timezone.utc)
