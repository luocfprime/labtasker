import os
import re
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional, Type, Union

from fastapi import HTTPException
from pydantic import TypeAdapter
from starlette.status import HTTP_400_BAD_REQUEST


def parse_timeout(timeout_str: str) -> float:
    """Convert timeout string to seconds.

    Supports formats:
    - Timeout in seconds: "1.5", "60"
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
    try:
        value = float(timeout_str)  # try directly as a number (in seconds)
        return value
    except (TypeError, ValueError):
        pass

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
        seconds = parse_timeout(timeout)
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


def auth_required(func):
    """
    A decorator to mark a function as requiring authentication.
    This does not enforce authentication but serves as a marker.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Just call the original function without enforcing anything
        return func(*args, **kwargs)

    # Add a marker attribute to the function
    wrapper.auth_required = True
    return wrapper


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


def arg_match(required, provided):
    """
    Check if all required arguments are provided in the provided arguments.
    Principle: No more, no less.
    """
    if required is None:  # Base case for recursion
        return True
    if provided is None:
        return False

    try:
        # Check if any required key is missing in provided (vice versa)
        if set(required.keys()) != set(provided.keys()):  # "No more, no less"
            return False
    except AttributeError:  # one of them is not dict
        return False

    # Recursively check each key and value pair
    for key, value in required.items():
        if not arg_match(value, provided[key]):
            return False

    return True


def keys_to_query_dict(keys):
    """
    Converts a list of dot-separated keys into a nested dictionary.
    Leaf node values are set to None.

    Args:
        keys (list): List of strings, where each string is a dot-separated key path.

    Returns:
        dict: Nested dictionary representation of the keys.
    """
    if not isinstance(keys, list):
        raise TypeError("Input must be a list of strings.")

    query_dict = {}

    for key in keys:
        if not isinstance(key, str):
            raise TypeError(f"Invalid key '{key}': Keys must be strings.")

        parts = key.split(".")  # Split the key into its parts
        current = query_dict

        for part in parts[:-1]:  # Traverse or create intermediate levels
            if (
                part not in current
                or current[part] is None  # leaf node exists: extend depth
            ):
                current[part] = {}
            current = current[part]

        if parts[-1] not in current:
            current[parts[-1]] = None  # Set the leaf node to None

    return query_dict


def sanitize_update(
    update: Dict[str, Any],
    banned_fields: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Ban update on certain fields."""

    if banned_fields is None:
        banned_fields = ["_id", "queue_id", "created_at", "last_modified"]

    def _recr_sanitize(d: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in d.items():
            if k in banned_fields:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail=f"Field {k} is not allowed to be updated",
                )
            elif isinstance(v, dict):
                d[k] = _recr_sanitize(v)
        return d

    return _recr_sanitize(update)


def sanitize_dict(dic: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a dictionary so that it does not contain any MongoDB operators."""

    def _recr_sanitize(d: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in d.items():
            if isinstance(k, str):
                if re.match(r"^\$", k):  # Match those starting with $
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"MongoDB operators are not allowed in field names: {k}",
                    )
                if k.startswith("."):
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"Field names starting with `.` are not allowed: {k}",
                    )
            if isinstance(v, dict):
                d[k] = _recr_sanitize(v)
        return d

    return _recr_sanitize(dic)


def parse_obj_as(dst_type: Type[Any], obj: Any) -> Any:
    return TypeAdapter(dst_type).validate_python(obj)
