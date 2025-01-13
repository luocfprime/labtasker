import os
import re
from datetime import datetime, timedelta, timezone
from functools import wraps
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
    """Get current UTC time."""
    return datetime.now(timezone.utc)


def flatten_dict(d, parent_key="", sep="."):
    """
    Flattens a nested dictionary into a single-level dictionary.

    Keys in the resulting dictionary use dot-notation to represent the nesting levels.

    Args:
        d (dict): The nested dictionary to flatten.
        parent_key (str, optional): The prefix for the keys (used during recursion). Defaults to ''.
        sep (str, optional): The separator to use for flattening keys. Defaults to '.'.

    Returns:
        dict: A flattened dictionary where nested keys are represented in dot-notation.

    Example:
        >>> nested_dict = {
        ...     "status": "completed",
        ...     "summary": {
        ...         "field1": "value1",
        ...         "nested": {
        ...             "subfield1": "subvalue1"
        ...         }
        ...     },
        ...     "retries": 3
        ... }
        >>> flatten_dict(nested_dict)
        {
            "status": "completed",
            "summary.field1": "value1",
            "summary.nested.subfield1": "subvalue1",
            "retries": 3
        }
    """
    items = []
    for k, v in d.items():
        # Combine parent key with current key using the separator
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            # Recur for nested dictionaries
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            # Add non-dictionary values to the result
            items.append((new_key, v))
    return dict(items)


def strtobool(val):
    """Convert a string representation of truth to true (1) or false (0).
    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.
    """
    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return 1
    elif val in ("n", "no", "f", "false", "off", "0"):
        return 0
    else:
        raise ValueError("invalid truth value %r" % (val,))


def risky(description: str):
    """Decorator to allow risky operations based on configuration.

    Args:
        description: Description of why this operation is risky

    Example:
        @risky("Direct database access bypassing FSM validation")
        def force_update_status():
            pass
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Check if unsafe behavior is allowed
            allow_unsafe = strtobool(
                os.getenv("ALLOW_UNSAFE_BEHAVIOR", "false").strip()
            )
            if not allow_unsafe:
                raise RuntimeError(
                    f"Unsafe behavior is not allowed: {description}\n"
                    "Set ALLOW_UNSAFE_BEHAVIOR=true to enable this operation."
                )
            return func(*args, **kwargs)

        # Extend docstring with description
        wrapper.__doc__ = f"{func.__doc__}\n\n[RISKY BEHAVIOR] {description}"
        return wrapper

    return decorator


# _api_usage_log = defaultdict(int)

# TODO: implement with logging for developers
# def log_api_usage(description: str):
#     """Decorator to log API usage."""
#     def decorator(func):
#         @wraps(func)
#         def wrapper(*args, **kwargs):
#             _api_usage_log[description] += 1
#             return func(*args, **kwargs)
#         return wrapper
#     return decorator
