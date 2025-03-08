import re
from typing import Any, Dict

from labtasker.client.core.exceptions import LabtaskerValueError
from labtasker.constants import DOT_SEPARATED_KEY_PATTERN
from labtasker.utils import flatten_dict


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
            raise LabtaskerValueError(
                f"Key '{key}' is not valid. Keys must be valid dot-separated strings. Got '{key}'"
            )
