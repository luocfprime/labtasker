import contextlib
import os
import re
from contextvars import ContextVar
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, Type, Union

from pydantic import TypeAdapter

from labtasker.constants import DOT_SEPARATED_KEY_PATTERN


def parse_time_interval(interval: str) -> float:
    """Convert time interval string to seconds.

    Supports formats:
    - Time in seconds: "1.5", "60"
    - Single unit: "1.5h", "30m", "60s"
    - Multiple units: "1h30m", "5m30s", "1h30m15s"
    - Full words: "1 hour", "30 minutes", "1 hour, 30 minutes"

    Args:
        interval: Time interval string to parse

    Returns:
        Number of seconds

    Raises:
        ValueError: If format is invalid
    """
    try:
        value = float(interval)  # try directly as a number (in seconds)
        return value
    except (TypeError, ValueError):
        pass

    if not interval or not isinstance(interval, str):
        raise ValueError("Time interval must be a non-empty string")

    # Clean up input
    interval = interval.lower().strip()
    interval = re.sub(r"[:,\s]+", "", interval)  # Remove all spaces, commas, and colons

    # Handle pure numbers (assume seconds)
    if interval.isdigit():
        return int(interval)

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

    total_seconds = 0.0

    # Match alternating number-unit pairs
    matches = re.findall(r"(\d+\.?\d*)([a-z]+)", interval)
    if not matches or "".join(num + unit for num, unit in matches) != interval:
        raise ValueError(f"Invalid time interval format: {interval}")

    for value_str, unit in matches:
        try:
            value = float(value_str)
        except ValueError:
            raise ValueError(f"Invalid number: {value_str}")

        if unit not in unit_map:
            raise ValueError(f"Invalid unit: {unit}")

        total_seconds += value * unit_map[unit]

    return total_seconds


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
        seconds = parse_time_interval(timeout)
        return timedelta(seconds=seconds)

    raise TypeError("Timeout must be an integer or string")


def _get_current_time(tz) -> datetime:
    return datetime.now(tz)


def get_current_time(tz=None) -> datetime:
    """Get current UTC time. Centralized time control."""
    return _get_current_time(tz)


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
        ...     "status": "success",
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
            "status": "success",
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


def unflatten_dict(d, sep="."):
    """
    Unflattens a flattened dictionary into a nested dictionary.

    Args:
        d (dict): The flattened dictionary to unflatten.
        sep (str, optional): The separator used for flattening keys. Defaults to '.'.

    Returns:
        dict: An unflattened dictionary where keys are represented in nested structures.

    Raises:
        ValueError: If there are conflicting keys, e.g., {"a": 1, "a.b": 2}.

    Example:
        >>> flattened_dict = {
        ...     "status": "success",
        ...     "summary.field1": "value1",
        ...     "summary.nested.subfield1": "subvalue1",
        ...     "retries": 3
        ... }
        >>> unflatten_dict(flattened_dict)
        {
            "status": "success",
            "summary": {
                "field1": "value1",
                "nested": {
                    "subfield1": "subvalue1"
                }
            },
            "retries": 3
        }
    """
    result = {}
    for key, value in d.items():
        keys = key.split(sep)  # Split the key by the separator
        current = result
        for part in keys[:-1]:  # Traverse/create nested dictionaries
            if part not in current:
                current[part] = {}
            elif not isinstance(current[part], dict):
                # Raise error if there's a conflict (e.g., {"a": 1, "a.b": 2})
                raise ValueError(
                    f"Conflict detected at key: {part}. Cannot merge nested and non-nested keys."
                )
            current = current[part]
        if keys[-1] in current and isinstance(current[keys[-1]], dict):
            # Raise error if there's a conflict (e.g., {"a.b": {}, "a.b.c": 1})
            raise ValueError(
                f"Conflict detected at key: {keys[-1]}. Cannot merge nested and non-nested keys."
            )
        current[keys[-1]] = value  # Set the final key to the value
    return result


def add_key_prefix(d: Dict[str, Any], prefix: str) -> Dict[str, Any]:
    """Add a prefix to all first level keys in a dictionary."""
    return {f"{prefix}{k}": v for k, v in d.items()}


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


def parse_obj_as(
    dst_type: Type[Any], obj: Any, check_unknown_fields_disabled: bool = True
) -> Any:
    """

    Args:
        dst_type:
        obj:
        check_unknown_fields_disabled: if True, api_models pydantic models does not check for unknown fields.

    Returns:

    """
    if check_unknown_fields_disabled:
        with disable_unknown_fields_check():
            return TypeAdapter(dst_type).validate_python(obj)

    return TypeAdapter(dst_type).validate_python(obj)


def validate_required_fields(keys):
    allowed_pattern = DOT_SEPARATED_KEY_PATTERN
    if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
        raise TypeError(f"Input must be a list of strings. Got {keys}.")
    if "*" not in keys and not all(re.match(allowed_pattern, k) for k in keys):
        raise ValueError(
            f"Keys must be valid dot-separated strings or a single '*' for matching everything. Got {keys}."
        )


def validate_dict_keys(d: Dict[str, Any]):
    """
    Only allow the same pattern of field names described in the lexer.
    e.g. foo_bar.baz, f1.f2

    Args:
        d:

    Returns:

    """
    allowed_pattern = DOT_SEPARATED_KEY_PATTERN
    keys = list(flatten_dict(d).keys())
    for key in keys:
        if not re.match(allowed_pattern, key):
            raise ValueError(
                f"Key '{key}' is not valid. Keys must be valid dot-separated strings. Got '{key}'"
            )


# A context flag to check whether to check for unknown fields
_disable_check_var: ContextVar[bool] = ContextVar(
    "disable_unknown_fields_check", default=False
)


@contextlib.contextmanager
def disable_unknown_fields_check():
    """Context manager to disable unknown fields check temporarily"""
    token = _disable_check_var.set(True)
    try:
        yield
    finally:
        _disable_check_var.reset(token)
