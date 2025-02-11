import pytest

from labtasker.utils import arg_match


@pytest.mark.unit
def test_exact_match():
    """Test when required and provided structures are exactly the same."""
    # leaf match
    required = {"arg1": None, "arg2": {"arg21": None}}
    provided = {"arg1": "value1", "arg2": {"arg21": "value2"}}
    assert arg_match(required, provided)

    # non-leaf match
    required = {"arg1": None, "arg2": None}
    provided = {"arg1": "value1", "arg2": "value2"}
    assert arg_match(required, provided)


@pytest.mark.unit
def test_missing_key():
    """Test when a required key is missing in provided."""
    required = {"arg1": None, "arg2": None}
    provided = {"arg1": "value1"}
    assert not arg_match(required, provided)


@pytest.mark.unit
def test_extra_key():
    """Test when provided has extra keys that are not in required."""
    required = {"arg1": None, "arg2": {"arg21": None}}
    provided = {"arg1": "value1", "arg2": {"arg21": "value2", "arg22": "extra"}}

    # reject the "no more" scenario, since "arg22" is "more"
    assert not arg_match(required, provided)


@pytest.mark.unit
def test_nested_structure_match():
    """Test nested structures when required and provided match."""
    required = {"arg1": None, "arg2": {"arg21": {"arg211": None}}}
    provided = {"arg1": "value1", "arg2": {"arg21": {"arg211": "value3"}}}
    assert arg_match(required, provided)


@pytest.mark.unit
def test_nested_structure_missing_key():
    """Test nested structures when a required nested key is missing."""
    required = {"arg1": None, "arg2": {"arg21": {"arg211": None}}}
    provided = {"arg1": "value1", "arg2": {"arg21": "value2"}}
    assert not arg_match(required, provided)


@pytest.mark.unit
def test_required_is_none():
    """Test when required is None (should always return True)."""
    required = None
    provided = {"arg1": "value1", "arg2": {"arg21": "value2"}}
    assert arg_match(required, provided)


@pytest.mark.unit
def test_provided_is_none():
    """Test when provided is None (should always return False unless required is None)."""
    required = {"arg1": None}
    provided = None
    assert not arg_match(required, provided)

    provided = {}
    assert not arg_match(required, provided)


@pytest.mark.unit
def test_empty_required_and_provided():
    """Test when both required and provided are empty dictionaries."""
    required = {}
    provided = {}
    assert not arg_match(required, provided)


@pytest.mark.unit
def test_empty_required_and_provided():
    """Test when both required and provided are empty dictionaries."""
    required = {"arg1": {"arg11": None}}
    provided = {"arg1": {"arg11": {}}}
    assert arg_match(required, provided)


@pytest.mark.unit
def test_empty_required_with_nonempty_provided():
    """Test when required is empty but provided has keys."""
    required = {}
    provided = {"arg1": "value1"}
    assert not arg_match(required, provided)


@pytest.mark.unit
def test_empty_provided_with_nonempty_required():
    """Test when required has keys but provided is empty."""
    required = {"arg1": None}
    provided = {}
    assert not arg_match(required, provided)
