from datetime import timedelta

import pytest

from labtasker.utils import flatten_dict, get_timeout_delta, parse_timeout


def test_parse_timeout_single_unit():
    """Test parsing single unit timeouts."""
    # Test hours
    assert parse_timeout("1h") == 3600
    assert parse_timeout("1.5h") == 5400
    assert parse_timeout("24h") == 86400
    assert parse_timeout("1 hour") == 3600
    assert parse_timeout("2 hours") == 7200

    # Test minutes
    assert parse_timeout("30m") == 1800
    assert parse_timeout("1.5m") == 90
    assert parse_timeout("60m") == 3600
    assert parse_timeout("1 minute") == 60
    assert parse_timeout("30 minutes") == 1800
    assert parse_timeout("30 min") == 1800

    # Test seconds
    assert parse_timeout("60s") == 60
    assert parse_timeout("1.5s") == 2
    assert parse_timeout("3600s") == 3600
    assert parse_timeout("60 seconds") == 60
    assert parse_timeout("1 second") == 1
    assert parse_timeout("30 sec") == 30


def test_parse_timeout_compound():
    """Test parsing compound timeouts."""
    assert parse_timeout("1h30m") == 5400
    assert parse_timeout("1 hour 30 minutes") == 5400
    assert parse_timeout("1 hour, 30 minutes") == 5400
    assert parse_timeout("1h, 30m") == 5400
    assert parse_timeout("1.5h 30m") == 5400 + 1800

    assert parse_timeout("5m30s") == 330
    assert parse_timeout("5 minutes 30 seconds") == 330
    assert parse_timeout("5 min, 30 sec") == 330

    assert parse_timeout("1h 30m 45s") == 5445
    assert parse_timeout("1 hour, 30 minutes, 45 seconds") == 5445


def test_parse_timeout_formatting():
    """Test timeout string formatting."""
    # Test whitespace handling
    assert parse_timeout(" 1h ") == 3600
    assert parse_timeout("2m  ") == 120
    assert parse_timeout("  1h  30m  ") == 5400

    # Test case insensitivity
    assert parse_timeout("1H") == 3600
    assert parse_timeout("30M") == 1800
    assert parse_timeout("1Hour") == 3600
    assert parse_timeout("1HOUR") == 3600

    # Test comma variations
    assert parse_timeout("1h, 30m") == 5400
    assert parse_timeout("1h,30m") == 5400
    assert parse_timeout("1 hour,30 minutes") == 5400


def test_parse_timeout_errors():
    """Test error handling in timeout parsing."""
    with pytest.raises(ValueError):
        parse_timeout("1d")  # Invalid unit

    with pytest.raises(ValueError):
        parse_timeout("abc")  # No number

    with pytest.raises(ValueError):
        parse_timeout("")  # Empty string

    with pytest.raises(ValueError):
        parse_timeout("1h30")  # Missing unit

    with pytest.raises(ValueError):
        parse_timeout(None)  # None input

    with pytest.raises(ValueError):
        parse_timeout("h1")  # Invalid unit


def test_get_timeout_delta():
    """Test converting timeouts to timedelta."""
    # Test with string timeouts
    assert get_timeout_delta("1.5h") == timedelta(seconds=5400)
    assert get_timeout_delta("1h 30m") == timedelta(seconds=5400)
    assert get_timeout_delta("1 hour, 30 minutes") == timedelta(seconds=5400)

    # Test with integer seconds
    assert get_timeout_delta(3600) == timedelta(hours=1)
    assert get_timeout_delta(5400) == timedelta(seconds=5400)

    # Test with zero
    assert get_timeout_delta(0) == timedelta(0)
    assert get_timeout_delta("0s") == timedelta(0)

    # Test invalid inputs
    with pytest.raises(ValueError):
        get_timeout_delta("invalid")

    with pytest.raises(ValueError):
        get_timeout_delta(1.5)  # Float not supported for direct seconds

    with pytest.raises(TypeError):
        get_timeout_delta(None)


def test_flatten_dict():
    """Test dictionary flattening with dot notation."""
    # Test case 1: Simple nested dictionary
    nested_dict = {
        "status": "completed",
        "summary": {"field1": "value1", "nested": {"subfield1": "subvalue1"}},
        "retries": 3,
    }

    expected = {
        "status": "completed",
        "summary.field1": "value1",
        "summary.nested.subfield1": "subvalue1",
        "retries": 3,
    }

    assert flatten_dict(nested_dict) == expected

    # Test case 2: Empty dictionary
    assert flatten_dict({}) == {}

    # Test case 3: Dictionary with no nesting
    flat_dict = {"a": 1, "b": 2, "c": 3}
    assert flatten_dict(flat_dict) == flat_dict

    # Test case 4: Dictionary with empty nested dictionaries
    nested_empty = {"a": {}, "b": {"c": {}}, "d": 1}
    assert flatten_dict(nested_empty) == {"d": 1}

    # Test case 5: Dictionary with custom separator
    nested_dict = {"a": {"b": {"c": 1}}}
    expected = {"a/b/c": 1}
    assert flatten_dict(nested_dict, sep="/") == expected

    # Test case 6: Dictionary with mixed value types
    mixed_dict = {
        "str": "string",
        "num": 42,
        "bool": True,
        "none": None,
        "nested": {"list": [1, 2, 3], "tuple": (4, 5, 6)},
    }
    expected = {
        "str": "string",
        "num": 42,
        "bool": True,
        "none": None,
        "nested.list": [1, 2, 3],
        "nested.tuple": (4, 5, 6),
    }
    assert flatten_dict(mixed_dict) == expected

    # Test case 7: Dictionary with prefix
    nested_dict = {"a": {"b": {"c": 1}}}

    prefix = "summary"
    expected = {"summary.a.b.c": 1}
    assert flatten_dict(nested_dict, parent_key=prefix) == expected
