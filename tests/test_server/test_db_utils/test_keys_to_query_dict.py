import pytest

from labtasker.server.db_utils import keys_to_query_dict


@pytest.mark.unit
@pytest.mark.parametrize(
    "keys",
    [
        # Invalid cases
        [""],  # Empty string
        ["."],  # Single dot
        [".*"],  # Invalid wildcard pattern
        ["field1..field2"],  # Double dots
        ["field1.field2."],  # Trailing dot
        [".field1"],
        [".."],
        ["*.field2"],  # Wildcard before field
        ["field1.*"],  # Wildcard after field
        ["#@$"],
        ["$"],
    ],
)
def test_keys_to_query_dict(keys):
    """
    Test the `keys_to_query_dict` function with various `keys` inputs.
    """
    for mode in ["deepest", "topmost"]:
        with pytest.raises(ValueError):
            keys_to_query_dict(keys, mode)
