import pytest

from labtasker.utils import flatten_dict, keys_to_query_dict


@pytest.mark.unit
def test_keys_to_query_dict_with_flatten_dict():
    """
    Test keys_to_query_dict using flatten_dict to generate input keys.
    """
    # Define a sample nested dictionary
    nested_dict = {
        "status": "success",
        "summary": {"field1": "value1", "nested": {"subfield1": "subvalue1"}},
        "retries": 3,
    }

    # Step 1: Flatten the nested dictionary to generate dot-separated keys
    flattened = flatten_dict(nested_dict)
    keys = list(flattened.keys())

    # Step 2: Use keys_to_query_dict to reconstruct the dictionary
    reconstructed_dict = keys_to_query_dict(keys)

    # Step 3: Define the expected dictionary with all leaf values set to None
    expected_dict = {
        "status": None,
        "summary": {"field1": None, "nested": {"subfield1": None}},
        "retries": None,
    }

    # Step 4: Assert that the reconstructed dictionary matches the expected dictionary
    assert (
        reconstructed_dict == expected_dict
    ), f"Reconstructed dictionary does not match expected. Got {reconstructed_dict}"


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
        # Test case 4: Overlapping keys
        (["arg1", "arg1.arg11"], {"arg1": {"arg11": None}}),
        # Test case 5: Empty input
        ([], {}),
        # Test case 6: Deep nesting
        (["a.b.c.d.e.f.g"], {"a": {"b": {"c": {"d": {"e": {"f": {"g": None}}}}}}}),
        # Test case 7: Nesting with longer prefix
        (
            ["arg1", "arg2.arg21", "arg2.arg22", "arg2.arg21.arg211"],
            {"arg1": None, "arg2": {"arg21": {"arg211": None}, "arg22": None}},
        ),
    ],
)
def test_keys_to_query_dict_edge_cases(keys, expected_dict):
    """
    Test keys_to_query_dict with various edge cases.
    """
    assert keys_to_query_dict(keys) == expected_dict


@pytest.mark.unit
def test_input_not_list():
    with pytest.raises(TypeError, match="Input must be a list of strings."):
        keys_to_query_dict("arg1.arg11")  # type: ignore


@pytest.mark.unit
def test_non_string_elements():
    with pytest.raises(TypeError, match="Invalid key '123': Keys must be strings."):
        keys_to_query_dict(["arg1", 123])
