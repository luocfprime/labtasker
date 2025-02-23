import pytest
import typer

from labtasker.client.core.cli_utils import parse_metadata


@pytest.mark.unit
def test_parse_metadata():
    """Test parsing metadata strings into dictionaries."""

    # Test valid metadata strings
    assert parse_metadata("{'key1': 'value1', 'key2': 2}") == {
        "key1": "value1",
        "key2": 2,
    }
    assert parse_metadata("{'key': {'nested_key': 'nested_value'}}") == {
        "key": {"nested_key": "nested_value"},
    }

    # Test empty metadata
    assert parse_metadata("") is None

    # Test invalid metadata strings
    with pytest.raises(typer.BadParameter):
        parse_metadata(
            "{'key1': 'value1', 'key2': 2},"
        )  # Trailing comma (Not a dictionary)

    with pytest.raises(typer.BadParameter):
        parse_metadata("{'key1': 'value1', 'key2': 2, 'key3':}")  # Missing value

    with pytest.raises(typer.BadParameter):
        parse_metadata("not a dict")  # Not a dictionary
