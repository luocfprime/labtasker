import pytest

from labtasker.server.db_utils import query_dict_to_mongo_filter


@pytest.mark.unit
def test_simple_query_dict():
    """
    Test with a simple query dict with no nesting.
    """
    query_dict = {"status": None, "retries": None}
    expected_filter = {"status": {"$exists": True}, "retries": {"$exists": True}}
    assert query_dict_to_mongo_filter(query_dict) == expected_filter


@pytest.mark.unit
def test_nested_query_dict():
    """
    Test with a nested query dict.
    """
    query_dict = {
        "summary": {"field1": None, "nested": {"subfield1": None}},
        "status": None,
    }
    expected_filter = {
        "summary.field1": {"$exists": True},
        "summary.nested.subfield1": {"$exists": True},
        "status": {"$exists": True},
    }
    assert query_dict_to_mongo_filter(query_dict) == expected_filter


@pytest.mark.unit
def test_empty_query_dict():
    """
    Test with an empty query dict.
    """
    query_dict = {}
    expected_filter = {}
    assert query_dict_to_mongo_filter(query_dict) == expected_filter


@pytest.mark.unit
def test_deeply_nested_query_dict():
    """
    Test with a deeply nested query dict.
    """
    query_dict = {"a": {"b": {"c": {"d": {"e": None}}}}}
    expected_filter = {"a.b.c.d.e": {"$exists": True}}
    assert query_dict_to_mongo_filter(query_dict) == expected_filter


@pytest.mark.unit
def test_query_dict_with_mixed_types():
    """
    Test with a query dict containing mixed value types (None, integers, strings).
    """
    query_dict = {
        "status": None,
        "retries": 3,
        "summary": {"field1": "value1", "nested": {"subfield1": None}},
    }
    expected_filter = {
        "status": {"$exists": True},
        "retries": {"$exists": True},
        "summary.field1": {"$exists": True},
        "summary.nested.subfield1": {"$exists": True},
    }
    assert query_dict_to_mongo_filter(query_dict) == expected_filter


@pytest.mark.unit
def test_query_dict_with_empty_nested_dict():
    """
    Test with a query dict containing an empty nested dictionary.
    """
    query_dict = {"summary": {}}
    expected_filter = {}
    assert query_dict_to_mongo_filter(query_dict) == expected_filter


@pytest.mark.unit
def test_query_dict_with_multiple_nested_fields():
    """
    Test with multiple nested fields at different levels.
    """
    query_dict = {
        "level1": {"level2": {"level3a": None, "level3b": {"level4": None}}},
        "status": None,
    }
    expected_filter = {
        "level1.level2.level3a": {"$exists": True},
        "level1.level2.level3b.level4": {"$exists": True},
        "status": {"$exists": True},
    }
    assert query_dict_to_mongo_filter(query_dict) == expected_filter
