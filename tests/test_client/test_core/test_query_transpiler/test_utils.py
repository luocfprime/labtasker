from copy import deepcopy

import pytest

from tests.test_client.test_core.test_query_transpiler.utils import (
    are_filters_equivalent,
)

pytestmark = [pytest.mark.unit]


class TestFilterEquivalence:
    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Empty filters
            ({}, {}, True),
            (None, {}, True),
            ({}, None, True),
            (None, None, True),
        ],
    )
    def test_empty_filters(self, filter1, filter2, expected):
        """Test empty filters are equivalent."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Identical filters
            ({"status": "active"}, {"status": "active"}, True),
            # Different filters
            ({"status": "active"}, {"status": "inactive"}, False),
            ({"status": "active"}, {"state": "active"}, False),
            # Different types
            ({"age": 25}, {"age": "25"}, False),
        ],
    )
    def test_simple_equality_filters(self, filter1, filter2, expected):
        """Test simple equality filters."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Same fields, same order
            (
                {"status": "active", "age": 25},
                {"status": "active", "age": 25},
                True,
            ),
            # Same fields, different order
            (
                {"status": "active", "age": 25},
                {"age": 25, "status": "active"},
                True,
            ),
            # Different fields
            (
                {"status": "active", "age": 25},
                {"status": "active", "level": 25},
                False,
            ),
        ],
    )
    def test_multiple_fields(self, filter1, filter2, expected):
        """Test filters with multiple fields."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Identical nested documents
            (
                {"address": {"city": "New York", "zip": "10001"}},
                {"address": {"city": "New York", "zip": "10001"}},
                True,
            ),
            # Same nested fields, different order
            (
                {"address": {"city": "New York", "zip": "10001"}},
                {"address": {"zip": "10001", "city": "New York"}},
                True,
            ),
            # Different nested fields
            (
                {"address": {"city": "New York", "zip": "10001"}},
                {"address": {"city": "Boston", "zip": "10001"}},
                False,
            ),
        ],
    )
    def test_nested_documents(self, filter1, filter2, expected):
        """Test filters with nested documents."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Identical comparison
            ({"age": {"$gt": 25}}, {"age": {"$gt": 25}}, True),
            # Multiple comparison operators, same order
            (
                {"age": {"$gt": 25, "$lt": 50}},
                {"age": {"$gt": 25, "$lt": 50}},
                True,
            ),
            # Multiple comparison operators, different order
            (
                {"age": {"$gt": 25, "$lt": 50}},
                {"age": {"$lt": 50, "$gt": 25}},
                True,
            ),
            # Different comparison values
            ({"age": {"$gt": 25}}, {"age": {"$gt": 30}}, False),
        ],
    )
    def test_comparison_operators(self, filter1, filter2, expected):
        """Test filters with comparison operators."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # $and with same conditions, same order
            (
                {"$and": [{"status": "active"}, {"age": {"$gt": 25}}]},
                {"$and": [{"status": "active"}, {"age": {"$gt": 25}}]},
                True,
            ),
            # $and with same conditions, different order
            (
                {"$and": [{"status": "active"}, {"age": {"$gt": 25}}]},
                {"$and": [{"age": {"$gt": 25}}, {"status": "active"}]},
                True,
            ),
            # $or with same conditions, different order
            (
                {"$or": [{"status": "active"}, {"age": {"$gt": 25}}]},
                {"$or": [{"age": {"$gt": 25}}, {"status": "active"}]},
                True,
            ),
            # $nor with same conditions, different order
            (
                {"$nor": [{"status": "inactive"}, {"age": {"$lt": 18}}]},
                {"$nor": [{"age": {"$lt": 18}}, {"status": "inactive"}]},
                True,
            ),
            # Different logical operators
            (
                {"$and": [{"status": "active"}, {"age": {"$gt": 25}}]},
                {"$or": [{"status": "active"}, {"age": {"$gt": 25}}]},
                False,
            ),
            # Different conditions
            (
                {"$and": [{"status": "active"}, {"age": {"$gt": 25}}]},
                {"$and": [{"status": "active"}, {"age": {"$gt": 30}}]},
                False,
            ),
        ],
    )
    def test_logical_operators(self, filter1, filter2, expected):
        """Test filters with logical operators ($and, $or, $nor)."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # $in with same values, same order
            (
                {"status": {"$in": ["active", "pending"]}},
                {"status": {"$in": ["active", "pending"]}},
                True,
            ),
            # $in with same values, different order
            (
                {"status": {"$in": ["active", "pending"]}},
                {"status": {"$in": ["pending", "active"]}},
                True,
            ),
            # $nin with same values, different order
            (
                {"status": {"$nin": ["inactive", "deleted"]}},
                {"status": {"$nin": ["deleted", "inactive"]}},
                True,
            ),
            # $all with same values, different order
            (
                {"tags": {"$all": ["mongodb", "database"]}},
                {"tags": {"$all": ["database", "mongodb"]}},
                True,
            ),
            # Different array operator values
            (
                {"status": {"$in": ["active", "pending"]}},
                {"status": {"$in": ["active", "completed"]}},
                False,
            ),
        ],
    )
    def test_array_operators(self, filter1, filter2, expected):
        """Test filters with array operators ($in, $nin, $all)."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Complex nested filter with logical operators
            (
                {
                    "$and": [
                        {"status": "active"},
                        {
                            "$or": [
                                {"age": {"$gt": 25}},
                                {"level": {"$in": ["advanced", "expert"]}},
                            ]
                        },
                        {"address.city": "New York"},
                    ]
                },
                {
                    "$and": [
                        {"address.city": "New York"},
                        {
                            "$or": [
                                {"level": {"$in": ["expert", "advanced"]}},
                                {"age": {"$gt": 25}},
                            ]
                        },
                        {"status": "active"},
                    ]
                },
                True,
            ),
            # Different filter with small change
            (
                {
                    "$and": [
                        {"status": "active"},
                        {
                            "$or": [
                                {"age": {"$gt": 25}},
                                {"level": {"$in": ["advanced", "expert"]}},
                            ]
                        },
                        {"address.city": "New York"},
                    ]
                },
                {
                    "$and": [
                        {"address.city": "New York"},
                        {
                            "$or": [
                                {"level": {"$in": ["intermediate", "advanced"]}},
                                {"age": {"$gt": 25}},
                            ]
                        },
                        {"status": "active"},
                    ]
                },
                False,
            ),
        ],
    )
    def test_complex_nested_filters(self, filter1, filter2, expected):
        """Test complex filters with multiple levels of nesting."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Simple $not
            (
                {"age": {"$not": {"$lt": 18}}},
                {"age": {"$not": {"$lt": 18}}},
                True,
            ),
            # $not with equivalent expressions
            (
                {"age": {"$not": {"$lt": 18}}},
                {"age": {"$gte": 18}},
                False,
            ),  # These are semantically equivalent but not structurally
            # Different $not conditions
            (
                {"age": {"$not": {"$lt": 18}}},
                {"age": {"$not": {"$lt": 21}}},
                False,
            ),
        ],
    )
    def test_not_operator(self, filter1, filter2, expected):
        """Test filters with $not operator."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # $exists
            (
                {"status": {"$exists": True}},
                {"status": {"$exists": True}},
                True,
            ),
            # $type
            (
                {"age": {"$type": "int"}},
                {"age": {"$type": "int"}},
                True,
            ),
            # Different $exists values
            (
                {"status": {"$exists": True}},
                {"status": {"$exists": False}},
                False,
            ),
        ],
    )
    def test_element_operators(self, filter1, filter2, expected):
        """Test filters with element operators ($exists, $type)."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Same regex
            (
                {"name": {"$regex": "^Jo", "$options": "i"}},
                {"name": {"$regex": "^Jo", "$options": "i"}},
                True,
            ),
            # Different regex
            (
                {"name": {"$regex": "^Jo", "$options": "i"}},
                {"name": {"$regex": "Jo$", "$options": "i"}},
                False,
            ),
        ],
    )
    def test_regex_operators(self, filter1, filter2, expected):
        """Test filters with regex operators."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Same expression
            (
                {"$expr": {"$gt": ["$price", "$cost"]}},
                {"$expr": {"$gt": ["$price", "$cost"]}},
                True,
            ),
            # Equivalent expression with different order in permutation-invariant operators
            (
                {"$expr": {"$and": [{"$gt": ["$price", 100]}, {"$lt": ["$cost", 50]}]}},
                {"$expr": {"$and": [{"$lt": ["$cost", 50]}, {"$gt": ["$price", 100]}]}},
                True,
            ),
            # Different expressions
            (
                {"$expr": {"$gt": ["$price", "$cost"]}},
                {"$expr": {"$gte": ["$price", "$cost"]}},
                False,
            ),
            # Different orders
            (
                {"$expr": {"$gt": ["$price", "$cost"]}},
                {"$expr": {"$gt": ["$cost", "$price"]}},
                False,
            ),
        ],
    )
    def test_expr_operator(self, filter1, filter2, expected):
        """Test filters with $expr operator."""
        assert are_filters_equivalent(filter1, filter2) == expected

    @pytest.mark.parametrize(
        "filter1, filter2, expected",
        [
            # Empty conditions in logical operators
            ({"$and": []}, {"$and": []}, True),
            # Deeply nested empty arrays/objects
            ({"nested": {"array": []}}, {"nested": {"array": []}}, True),
            # Mixed types that should not be equivalent
            ({"tags": ["a", "b"]}, {"tags": {"$in": ["a", "b"]}}, False),
        ],
    )
    def test_edge_cases(self, filter1, filter2, expected):
        """Test edge cases and unusual filters."""
        assert are_filters_equivalent(filter1, filter2) == expected

    def test_mutation_safety(self):
        """Test that the original filters are not modified."""
        filter1 = {"$and": [{"a": 1}, {"b": 2}]}
        filter2 = {"$and": [{"b": 2}, {"a": 1}]}

        # Make deep copies to verify later
        filter1_copy = deepcopy(filter1)
        filter2_copy = deepcopy(filter2)

        # Test equivalence
        assert are_filters_equivalent(filter1, filter2)

        # Verify originals weren't changed
        assert filter1 == filter1_copy
        assert filter2 == filter2_copy
