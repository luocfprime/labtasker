import pytest

from labtasker.server.db_utils import keys_to_query_dict


@pytest.mark.unit
@pytest.mark.parametrize(
    "keys,expected_dict",
    [
        # Test case 1: Single key
        (["arg1"], {"arg1": None}),
        # Test case 2: Multiple keys, no nesting
        (["arg1", "arg2"], {"arg1": None, "arg2": None}),
        # Test case 3: Nested keys
        (["arg1.arg11.arg111"], {"arg1": {"arg11": {"arg111": None}}}),
        # Test case 4: Overlapping keys - topmost should keep shortest path
        (["arg1", "arg1.arg11"], {"arg1": None}),
        # Test case 5: Empty input
        ([], {}),
        # Test case 6: Deep nesting
        (["a.b.c.d.e.f.g"], {"a": {"b": {"c": {"d": {"e": {"f": {"g": None}}}}}}}),
        # Test case 7: Nesting with multiple overlapping paths
        (
            ["arg1", "arg2.arg21", "arg2.arg22", "arg2.arg21.arg211"],
            {"arg1": None, "arg2": {"arg21": None, "arg22": None}},
        ),
        # Test case 8: Multiple overlapping paths
        (
            ["a.b", "a.b.c", "a.b.d", "x.y.z"],
            {"a": {"b": None}, "x": {"y": {"z": None}}},
        ),
        # Test case 9: Paths with same prefix but different lengths
        (
            ["user", "user.name", "user.address.city", "user.address"],
            {"user": None},
        ),
    ],
)
def test_keys_to_query_dict_topmost_mode(keys, expected_dict):
    """
    Test keys_to_query_dict with mode="topmost" to ensure the shortest paths are preserved.
    """
    result = keys_to_query_dict(keys, mode="topmost")
    assert result == expected_dict, f"Expected {expected_dict}, but got {result}"
