import pytest
import typer

from labtasker import LabtaskerValueError
from labtasker.client.core.cli_utils import (
    parse_extra_opt,
    parse_metadata,
    parse_updates,
)


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


@pytest.mark.unit
class TestParseExtraOpt:
    def test_long_options_basic(self):
        args = ["--arg1", "value1", "--arg2=42", "--flag"]
        result = parse_extra_opt(args, ignore_flag_options=False)
        expected = {
            "arg1": "value1",
            "arg2": 42,
            "flag": True,
        }
        assert result == expected

    @pytest.mark.parametrize(
        "args, expected",
        [
            # Basic key-value pairs and flags
            (
                ["--arg1", "value1", "--arg2=42", "--flag"],
                {"arg1": "value1", "arg2": 42},
            ),
            # Key-value pairs with dashes in names
            (
                ["--foo-bar=baz", "--another-Arg", "value"],
                {"foo_bar": "baz", "another_Arg": "value"},
            ),
            # Multiple keys with special characters
            (
                ["--special-chars='hello world'", "--path=/some/path"],
                {"special_chars": "hello world", "path": "/some/path"},
            ),
            # Quoted strings
            (
                ["--key1", '"value with spaces"', "--key2='single quoted'"],
                {"key1": "value with spaces", "key2": "single quoted"},
            ),
            # Empty input
            (
                [],
                {},
            ),
        ],
    )
    def test_long_options(self, args, expected):
        result = parse_extra_opt(args)
        assert result == expected

    def test_long_options_with_dots(self):
        args = ["--foo.bar", "value", "--nested.key.subkey=123"]
        result = parse_extra_opt(args)
        expected = {
            "foo": {"bar": "value"},
            "nested": {"key": {"subkey": 123}},
        }
        assert result == expected

    def test_short_options(self):
        args = ["-a", "-b", "value", "-c"]
        result = parse_extra_opt(args, ignore_flag_options=False)
        expected = {
            "a": True,
            "b": "value",
            "c": True,
        }
        assert result == expected

    def test_grouped_short_options(self):
        args = ["-abc"]
        result = parse_extra_opt(args, ignore_flag_options=False)
        expected = {"a": True, "b": True, "c": True}
        assert result == expected

    def test_ignore_flag_options(self):
        args = ["-abc", "--flag", "--foo", "hi"]
        result = parse_extra_opt(args, ignore_flag_options=True)
        expected = {"foo": "hi"}
        assert result == expected

    def test_quoted_values(self):
        args = ["--name", '"John Doe"', "--path", "/home/user/path"]
        result = parse_extra_opt(args)
        expected = {
            "name": "John Doe",
            "path": "/home/user/path",
        }
        assert result == expected

    def test_primitive_value_conversion(self):
        args = ["--list", "[1,2,3]", "--integer", "42", "--boolean", "True"]
        result = parse_extra_opt(args)
        expected = {
            "list": [1, 2, 3],
            "integer": 42,
            "boolean": True,
        }
        assert result == expected

    def test_unexpected_token(self):
        args = ["unexpected_token", "--arg1", "value"]
        with pytest.raises(ValueError, match=r"Unexpected token: unexpected_token"):
            parse_extra_opt(args)

    def test_flag_with_ignore_flag_options_false(self):
        args = ["--flag"]
        result = parse_extra_opt(args, ignore_flag_options=False)
        expected = {"flag": True}
        assert result == expected

    def test_flag_with_ignore_flag_options_true(self):
        args = ["--flag"]
        result = parse_extra_opt(args, ignore_flag_options=True)
        expected = {}
        assert result == expected


@pytest.mark.unit
class TestParseUpdates:
    def test_valid_updates_with_normalization(self):
        updates = ["args.arg-foo=42", "metadata.label=test"]
        top_level_fields = ["args", "metadata"]
        replace_fields, update_dict = parse_updates(
            updates, top_level_fields, normalize_dash=True
        )

        assert replace_fields == []
        assert update_dict == {
            "args": {"arg_foo": 42},
            "metadata": {"label": "test"},
        }

    def test_valid_updates_without_normalization(self):
        updates = ["args.arg-foo=42", "metadata.label=test"]
        top_level_fields = ["args", "metadata"]
        replace_fields, update_dict = parse_updates(
            updates, top_level_fields, normalize_dash=False
        )

        assert replace_fields == []
        assert update_dict == {
            "args": {"arg-foo": 42},
            "metadata": {"label": "test"},
        }

    def test_invalid_update_missing_value(self):
        updates = ["args.arg-foo"]
        top_level_fields = ["args"]
        with pytest.raises(
            LabtaskerValueError, match=r"Invalid update: args.arg-foo. Got \(.*\)"
        ):
            parse_updates(updates, top_level_fields)

    def test_invalid_update_no_matching_pattern(self):
        updates = ["-args.arg-foo=42"]
        top_level_fields = ["args"]
        with pytest.raises(LabtaskerValueError):
            parse_updates(updates, top_level_fields)

    def test_replace_top_level_field(self):
        updates = ["args=42", "metadata=test"]
        top_level_fields = ["args", "metadata"]
        replace_fields, update_dict = parse_updates(updates, top_level_fields)

        assert replace_fields == ["args", "metadata"]
        assert update_dict == {"args": 42, "metadata": "test"}

    def test_subfields_update(self):
        updates = ["args.foo.bar=42"]
        top_level_fields = ["args"]
        replace_fields, update_dict = parse_updates(updates, top_level_fields)

        assert replace_fields == []
        assert update_dict == {"args": {"foo.bar": 42}}

    def test_invalid_top_level_field(self):
        updates = ["invalid.field=42"]
        top_level_fields = ["args"]
        with pytest.raises(LabtaskerValueError):
            parse_updates(updates, top_level_fields)

    def test_edge_case_empty_updates(self):
        updates = []
        top_level_fields = ["args", "metadata"]
        replace_fields, update_dict = parse_updates(updates, top_level_fields)

        assert replace_fields == []
        assert update_dict == {}

    def test_edge_case_empty_top_level_fields(self):
        updates = ["args.arg-foo=42"]
        top_level_fields = []
        with pytest.raises(LabtaskerValueError):
            parse_updates(updates, top_level_fields)

    def test_no_to_primitive(self):
        updates = ["args.arg-foo=42"]
        top_level_fields = ["args"]
        replace_fields, update_dict = parse_updates(
            updates, top_level_fields, to_primitive=False
        )
        assert replace_fields == []
        assert update_dict == {"args": {"arg_foo": "42"}}

    def test_no_normalize_dash(self):
        updates = ["args.arg-foo=42"]
        top_level_fields = ["args"]
        replace_fields, update_dict = parse_updates(
            updates, top_level_fields, normalize_dash=False
        )
        assert replace_fields == []
        assert update_dict == {"args": {"arg-foo": 42}}

    def test_string_with_quotes(self):
        updates = ["args.arg-str='test'"]
        top_level_fields = ["args"]
        replace_fields, update_dict = parse_updates(updates, top_level_fields)
        assert replace_fields == []
        assert update_dict == {"args": {"arg_str": "test"}}
