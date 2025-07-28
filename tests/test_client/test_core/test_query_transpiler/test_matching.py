import datetime
from datetime import timezone

import pytest

from labtasker.client.core.exceptions import (
    QueryTranspilerSyntaxError,
    QueryTranspilerValueError,
)
from labtasker.client.core.query_transpiler import transpile_query
from tests.test_client.test_core.test_query_transpiler.utils import (
    are_filters_equivalent,
)

pytestmark = [pytest.mark.unit]


class TestQueryTranspiler:
    """Test cases for the QueryTranspiler class"""

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            ("foo == 42", {"foo": 42}),
            ("foo.bar == 42", {"foo.bar": 42}),
            ("foo['bar'] == 42", {"foo.bar": 42}),
            ("foo[0] == 42", {"foo.0": 42}),
            ("foo['bar']['baz'] == 42", {"foo.bar.baz": 42}),
            ("foo.bar[0] == 42", {"foo.bar.0": 42}),
            ("foo.bar[0]['baz'] == 42", {"foo.bar.0.baz": 42}),
            ("foo[0].bar == 42", {"foo.0.bar": 42}),
        ],
    )
    def test_field_conversion(self, query_str, expected_result):
        """Test converting dot separated fields and subscript. E.g. foo.bar, foo['bar']"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str",
        [
            "foo[bar] == 42",
            "foo[-1] == 0",  # negative indexing is not supported
        ],
    )
    def test_invalid_field_conversion(self, query_str):
        """Test invalid conversion of dot separated fields and subscript."""
        with pytest.raises(QueryTranspilerValueError):
            transpile_query(query_str)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # Greater than (auto added $exists check before evaluating $expr)
            ("age > 18", {"age": {"$gt": 18}}),
            (
                "foo > bar",
                {
                    "$and": [
                        {"foo": {"$exists": True}},
                        {"bar": {"$exists": True}},
                        {"$expr": {"$gt": ["$foo", "$bar"]}},
                    ]
                },
            ),
            # With nested fields
            (
                "foo.a > bar.b",
                {
                    "$and": [
                        {"bar.b": {"$exists": True}},
                        {"foo.a": {"$exists": True}},
                        {"$expr": {"$gt": ["$foo.a", "$bar.b"]}},
                    ]
                },
            ),
            # Greater than or equal
            ("age >= 18", {"age": {"$gte": 18}}),
            # Less than
            ("age < 18", {"age": {"$lt": 18}}),
            # Less than or equal
            ("args.age <= 18", {"args.age": {"$lte": 18}}),
            # Equal to
            ("age == 18", {"age": 18}),
            # # Not equal to (no longer supported due to ambiguity)
            # ("age != 18", {"age": {"$ne": 18}}),
            # Reverse orders
            ("18 < age", {"age": {"$gt": 18}}),
            # ("18 != age", {"age": {"$ne": 18}}), # (no longer supported due to ambiguity)
            ("18 == age", {"age": 18}),
            # Reverse orders with nested fields
            ("18 < age.foo", {"age.foo": {"$gt": 18}}),
            # ("18 != age.bar", {"age.bar": {"$ne": 18}}), # (no longer supported due to ambiguity)
            ("18 == age.foo", {"age.foo": 18}),
        ],
    )
    def test_comparison_operators(self, query_str, expected_result):
        """Test basic comparison operators with parameterized test cases"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            ("name == 'John'", {"name": "John"}),
            # ("name != 'John'", {"name": {"$ne": "John"}}), # (no longer supported due to ambiguity)
        ],
    )
    def test_string_comparisons(self, query_str, expected_result):
        """Test comparisons with string literals"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # AND
            (
                "age > 18 and 'John' == name.first",
                {"$and": [{"age": {"$gt": 18}}, {"name.first": "John"}]},
            ),
            # OR
            (
                "age < 18 or name.first == 'John'",
                {"$or": [{"age": {"$lt": 18}}, {"name.first": "John"}]},
            ),
            # # NOT (is not supported due to the potential ambiguity)
            # ("not age > 18", {"$not": {"age": {"$gt": 18}}}),
        ],
    )
    def test_logical_operators(self, query_str, expected_result):
        """Test logical operators (AND, OR, NOT)"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # AND with multiple conditions
            (
                "age.a > 18 and 65 > age.b and status == 'active'",
                {
                    "$and": [
                        {"age.a": {"$gt": 18}},
                        {"age.b": {"$lt": 65}},
                        {"status": "active"},
                    ]
                },
            ),
            # OR with multiple conditions
            (
                "status == 'pending' or status == 'active' or status == 'suspended'",
                {
                    "$or": [
                        {"status": "pending"},
                        {"status": "active"},
                        {"status": "suspended"},
                    ]
                },
            ),
            # Nested logical operations
            (
                "(age > 18 and age < 65) or status == 'special'",
                {
                    "$or": [
                        {"$and": [{"age": {"$gt": 18}}, {"age": {"$lt": 65}}]},
                        {"status": "special"},
                    ]
                },
            ),
        ],
    )
    def test_complex_logical_expressions(self, query_str, expected_result):
        """Test complex combinations of logical operators"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            (
                "status in ['active', 'pending']",
                {"status": {"$in": ["active", "pending"]}},
            ),
            (
                "'experimental' in dict(metadata.tags)",
                {"metadata.tags.experimental": {"$exists": True}},
            ),
            (
                "'experimental' in list(metadata.tags)",
                {"metadata.tags": "experimental"},
            ),
            # not supported due to ambiguity
            # (
            #     "status not in ['suspended', 'inactive']",
            #     {"status": {"$nin": ["suspended", "inactive"]}},
            # ),
        ],
    )
    def test_membership_operators(self, query_str, expected_result):
        """Test 'in' and 'not in' operators"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # regex
            ("regex(name, '^J.*')", {"name": {"$regex": "^J.*"}}),
            # exists
            ("exists(email)", {"email": {"$exists": True}}),
            # # not exists ('not' is not supported due to the potential ambiguity)
            # ("not exists(phone)", {"$not": {"phone": {"$exists": True}}}),
            # alternatively
            ("exists(foo.bar, False)", {"foo.bar": {"$exists": False}}),
            # function call on both sides
            (
                "regex(name, '^J.*') and exists(email)",
                {"$and": [{"name": {"$regex": "^J.*"}}, {"email": {"$exists": True}}]},
            ),
            # date
            (
                "last_modified > date('2025/7/25 23:41')",
                {
                    "last_modified": {
                        "$gt": datetime.datetime(2025, 7, 25, 23, 41).astimezone(
                            timezone.utc
                        )
                    }
                },
            ),
        ],
    )
    def test_special_functions(self, query_str, expected_result):
        """Test special functions (regex, exists)"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # Integers
            ("age == 18", {"age": 18}),
            # Floats
            ("score == 9.5", {"score": 9.5}),
            # Strings
            ("name == 'John'", {"name": "John"}),
            # Booleans
            ("active == True", {"active": True}),
            ("active == False", {"active": False}),
            # None/null
            ("value == None", {"value": None}),
            # Lists
            ("tags == ['python', 'mongodb']", {"tags": ["python", "mongodb"]}),
            # Dicts
            (
                "info == {'name': 'John', 'age': 18}",
                {"info": {"name": "John", "age": 18}},
            ),
            # not supported due to ambiguity
            # (
            #     "info != {'name': 'John', 'age': 18}",
            #     {"info": {"$ne": {"name": "John", "age": 18}}},
            # ),
        ],
    )
    def test_literals_comparisons(self, query_str, expected_result):
        """Test various literal types"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_error",
        [
            # Invalid logical operator
            ("18 is age", QueryTranspilerValueError),
            # Chained comparisons
            ("18 < age < 65", QueryTranspilerValueError),
            # Invalid function call
            ("unknown_function(field, value)", QueryTranspilerValueError),
            # Function with wrong number of arguments
            ("regex(name)", QueryTranspilerValueError),
            # Non-expression input
            ("def func(): pass", QueryTranspilerValueError),
            # Empty input
            ("", QueryTranspilerValueError),
            # Single input
            ("foo.bar", QueryTranspilerValueError),
            # String input
            ("'a string'", QueryTranspilerValueError),
            # Syntax error
            ("foo.bar - < ,", QueryTranspilerSyntaxError),
        ],
    )
    def test_invalid_expressions(self, query_str, expected_error):
        """Test invalid expressions that should raise errors"""
        with pytest.raises(expected_error):
            transpile_query(query_str)

    @pytest.mark.parametrize(
        "query_str1, query_str2",
        [
            ("age>18", "age > 18"),
            ("age>18 and name=='John'", "age > 18 and name == 'John'"),
        ],
    )
    def test_whitespace_handling_equivalence(self, query_str1, query_str2):
        """Test that different whitespace patterns yield the same result"""
        assert transpile_query(query_str1) == transpile_query(query_str2)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            (
                """
                (
                    age > 18 and
                    name == 'John' and
                    status == 'active'
                )
                """,
                {
                    "$and": [
                        {"age": {"$gt": 18}},
                        {"name": "John"},
                        {"status": "active"},
                    ]
                },
            ),
        ],
    )
    def test_multiline_queries(self, query_str, expected_result):
        """Test multiline queries"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            (
                "(((age > 18) and (name == 'John')) or ((status == 'special') and (score > 90)))",
                {
                    "$or": [
                        {"$and": [{"age": {"$gt": 18}}, {"name": "John"}]},
                        {"$and": [{"status": "special"}, {"score": {"$gt": 90}}]},
                    ]
                },
            ),
        ],
    )
    def test_nested_expressions(self, query_str, expected_result):
        """Test deeply nested expressions"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # Empty lists
            ("tags in []", {"tags": {"$in": []}}),
            # Single item lists
            ("status in ['active']", {"status": {"$in": ["active"]}}),
            # Unicode strings
            ("name == '你好'", {"name": "你好"}),
            # Special characters in field names
            ("user_details.name == 'John'", {"user_details.name": "John"}),
            # Escaped strings
            ("path == 'C:\\\\Users\\\\John'", {"path": "C:\\Users\\John"}),
        ],
    )
    def test_edge_cases(self, query_str, expected_result):
        """Test various edge cases"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)


class TestExprQueries:
    """Test class for MongoDB $expr expression queries
    Notes: For $expr, it is essential to make sure keys exist before evaluating.
    Otherwise, it may lead to (foo.bar >= foo.baz) returning True even if foo.bar and foo.baz may not exist.
    """

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # Addition with $exists checks
            (
                "a + b > c",
                {
                    "$and": [
                        {"c": {"$exists": True}},
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {"$expr": {"$gt": [{"$add": ["$a", "$b"]}, "$c"]}},
                    ]
                },
            ),
            # Subtraction with $exists checks
            (
                "price - discount < maxPrice",
                {
                    "$and": [
                        {"maxPrice": {"$exists": True}},
                        {"discount": {"$exists": True}},
                        {"price": {"$exists": True}},
                        {
                            "$expr": {
                                "$lt": [
                                    {"$subtract": ["$price", "$discount"]},
                                    "$maxPrice",
                                ]
                            }
                        },
                    ]
                },
            ),
            # Multiplication with $exists checks
            (
                "quantity * price > 1000",
                {
                    "$and": [
                        {"price": {"$exists": True}},
                        {"quantity": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [{"$multiply": ["$quantity", "$price"]}, 1000]
                            }
                        },
                    ]
                },
            ),
            # Division with $exists checks
            (
                "total / count < 50",
                {
                    "$and": [
                        {"count": {"$exists": True}},
                        {"total": {"$exists": True}},
                        {"$expr": {"$lt": [{"$divide": ["$total", "$count"]}, 50]}},
                    ]
                },
            ),
            # Modulo with $exists check
            (
                "value % 10 == 0",
                {
                    "$and": [
                        {"value": {"$exists": True}},
                        {"$expr": {"$eq": [{"$mod": ["$value", 10]}, 0]}},
                    ]
                },
            ),
            # Nested operations with $exists checks
            (
                "(a + b) * c > 100",
                {
                    "$and": [
                        {"c": {"$exists": True}},
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {"$multiply": [{"$add": ["$a", "$b"]}, "$c"]},
                                    100,
                                ]
                            }
                        },
                    ]
                },
            ),
            (
                "price + (tax * 0.1) > totalBudget",
                {
                    "$and": [
                        {"totalBudget": {"$exists": True}},
                        {"tax": {"$exists": True}},
                        {"price": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {"$add": ["$price", {"$multiply": ["$tax", 0.1]}]},
                                    "$totalBudget",
                                ]
                            }
                        },
                    ]
                },
            ),
            # Equal comparison with $exists checks
            (
                "a + b == c",
                {
                    "$and": [
                        {"c": {"$exists": True}},
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {"$expr": {"$eq": [{"$add": ["$a", "$b"]}, "$c"]}},
                    ]
                },
            ),
            # Greater than or equal comparison with $exists checks
            (
                "p + q >= r",
                {
                    "$and": [
                        {"r": {"$exists": True}},
                        {"q": {"$exists": True}},
                        {"p": {"$exists": True}},
                        {"$expr": {"$gte": [{"$add": ["$p", "$q"]}, "$r"]}},
                    ]
                },
            ),
            # Less than or equal comparison with $exists checks
            (
                "m + n <= o",
                {
                    "$and": [
                        {"o": {"$exists": True}},
                        {"n": {"$exists": True}},
                        {"m": {"$exists": True}},
                        {"$expr": {"$lte": [{"$add": ["$m", "$n"]}, "$o"]}},
                    ]
                },
            ),
            # Mixed with constants and $exists checks
            (
                "field + 10 > threshold",
                {
                    "$and": [
                        {"threshold": {"$exists": True}},
                        {"field": {"$exists": True}},
                        {"$expr": {"$gt": [{"$add": ["$field", 10]}, "$threshold"]}},
                    ]
                },
            ),
            (
                "price * 1.2 < maxPrice",
                {
                    "$and": [
                        {"maxPrice": {"$exists": True}},
                        {"price": {"$exists": True}},
                        {
                            "$expr": {
                                "$lt": [{"$multiply": ["$price", 1.2]}, "$maxPrice"]
                            }
                        },
                    ]
                },
            ),
            # Multiple operations with $exists checks
            (
                "a + b * c / d > threshold",
                {
                    "$and": [
                        {"threshold": {"$exists": True}},
                        {"d": {"$exists": True}},
                        {"c": {"$exists": True}},
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {
                                        "$add": [
                                            "$a",
                                            {
                                                "$divide": [
                                                    {"$multiply": ["$b", "$c"]},
                                                    "$d",
                                                ]
                                            },
                                        ]
                                    },
                                    "$threshold",
                                ]
                            }
                        },
                    ]
                },
            ),
            # Logical operators with expressions and $exists checks
            (
                "a + b > c and x + y < z",
                {
                    "$and": [
                        {
                            "$and": [
                                {"c": {"$exists": True}},
                                {"b": {"$exists": True}},
                                {"a": {"$exists": True}},
                                {"$expr": {"$gt": [{"$add": ["$a", "$b"]}, "$c"]}},
                            ]
                        },
                        {
                            "$and": [
                                {"z": {"$exists": True}},
                                {"y": {"$exists": True}},
                                {"x": {"$exists": True}},
                                {"$expr": {"$lt": [{"$add": ["$x", "$y"]}, "$z"]}},
                            ]
                        },
                    ]
                },
            ),
            # Mixed expr and regular queries with $exists checks
            (
                "(price + tax > 100) and (category == 'electronics')",
                {
                    "$and": [
                        {
                            "$and": [
                                {"price": {"$exists": True}},
                                {"tax": {"$exists": True}},
                                {"$expr": {"$gt": [{"$add": ["$price", "$tax"]}, 100]}},
                            ]
                        },
                        {"category": "electronics"},
                    ]
                },
            ),
            (
                "price * quantity > budget or discount > 10",
                {
                    "$or": [
                        {
                            "$and": [
                                {"budget": {"$exists": True}},
                                {"quantity": {"$exists": True}},
                                {"price": {"$exists": True}},
                                {
                                    "$expr": {
                                        "$gt": [
                                            {"$multiply": ["$price", "$quantity"]},
                                            "$budget",
                                        ]
                                    }
                                },
                            ]
                        },
                        {"discount": {"$gt": 10}},
                    ]
                },
            ),
            # Simple negation with field and constant
            (
                "a < -10",
                {"a": {"$lt": -10}},
            ),
            (
                "-10 > a",
                {"a": {"$lt": -10}},
            ),
            # Negation with field reference
            (
                "a < -b",
                {
                    "$and": [
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {"$expr": {"$lt": ["$a", {"$multiply": [-1, "$b"]}]}},
                    ]
                },
            ),
            # Negation with expression
            (
                "a < -(b + c)",
                {
                    "$and": [
                        {"c": {"$exists": True}},
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {
                            "$expr": {
                                "$lt": [
                                    "$a",
                                    {"$multiply": [-1, {"$add": ["$b", "$c"]}]},
                                ]
                            }
                        },
                    ]
                },
            ),
            # Double negation
            (
                "a > -(-b)",
                {
                    "$and": [
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    "$a",
                                    {"$multiply": [-1, {"$multiply": [-1, "$b"]}]},
                                ]
                            }
                        },
                    ]
                },
            ),
            # Negation with arithmetic operation on right side
            (
                "total > -(price * quantity)",
                {
                    "$and": [
                        {"quantity": {"$exists": True}},
                        {"price": {"$exists": True}},
                        {"total": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    "$total",
                                    {
                                        "$multiply": [
                                            -1,
                                            {"$multiply": ["$price", "$quantity"]},
                                        ]
                                    },
                                ]
                            }
                        },
                    ]
                },
            ),
            # Negation on left side
            (
                "-a > b",
                {
                    "$and": [
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {"$expr": {"$gt": [{"$multiply": [-1, "$a"]}, "$b"]}},
                    ]
                },
            ),
            # Negation on both sides
            (
                "-a < -b",
                {
                    "$and": [
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {
                            "$expr": {
                                "$lt": [
                                    {"$multiply": [-1, "$a"]},
                                    {"$multiply": [-1, "$b"]},
                                ]
                            }
                        },
                    ]
                },
            ),
            # Negative constant in an expression
            (
                "a + (-5) > b",
                {
                    "$and": [
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {"$expr": {"$gt": [{"$add": ["$a", -5]}, "$b"]}},
                    ]
                },
            ),
            # Complex expression with negation
            (
                "a + b > -(c * d)",
                {
                    "$and": [
                        {"d": {"$exists": True}},
                        {"c": {"$exists": True}},
                        {"b": {"$exists": True}},
                        {"a": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {"$add": ["$a", "$b"]},
                                    {"$multiply": [-1, {"$multiply": ["$c", "$d"]}]},
                                ]
                            }
                        },
                    ]
                },
            ),
            # Logical operators with negated expressions
            (
                "a > -b and c < -d",
                {
                    "$and": [
                        {
                            "$and": [
                                {"b": {"$exists": True}},
                                {"a": {"$exists": True}},
                                {"$expr": {"$gt": ["$a", {"$multiply": [-1, "$b"]}]}},
                            ]
                        },
                        {
                            "$and": [
                                {"d": {"$exists": True}},
                                {"c": {"$exists": True}},
                                {"$expr": {"$lt": ["$c", {"$multiply": [-1, "$d"]}]}},
                            ]
                        },
                    ]
                },
            ),
            # Negation with more complex arithmetic
            (
                "total > -(base + tax) * rate",
                {
                    "$and": [
                        {"rate": {"$exists": True}},
                        {"tax": {"$exists": True}},
                        {"base": {"$exists": True}},
                        {"total": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    "$total",
                                    {
                                        "$multiply": [
                                            {
                                                "$multiply": [
                                                    -1,
                                                    {"$add": ["$base", "$tax"]},
                                                ]
                                            },
                                            "$rate",
                                        ]
                                    },
                                ]
                            }
                        },
                    ]
                },
            ),
        ],
    )
    def test_expr_queries(self, query_str, expected_result):
        """Test queries involving MongoDB $expr operator with $exists conditions"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "query_str, expected_result",
        [
            # Basic field access with dot notation
            (
                "foo.bar > foo.baz",
                {
                    "$and": [
                        {"foo.baz": {"$exists": True}},
                        {"foo.bar": {"$exists": True}},
                        {"$expr": {"$gt": ["$foo.bar", "$foo.baz"]}},
                    ]
                },
            ),
            # Arithmetic with nested fields
            (
                "user.profile.age + 5 > user.settings.ageLimit",
                {
                    "$and": [
                        {"user.settings.ageLimit": {"$exists": True}},
                        {"user.profile.age": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {"$add": ["$user.profile.age", 5]},
                                    "$user.settings.ageLimit",
                                ]
                            }
                        },
                    ]
                },
            ),
            # Bracket notation for field access
            (
                "foo['bar'] == foo['baz']",
                {
                    "$and": [
                        {"foo.baz": {"$exists": True}},
                        {"foo.bar": {"$exists": True}},
                        {"$expr": {"$eq": ["$foo.bar", "$foo.baz"]}},
                    ]
                },
            ),
            # Mixed dot and bracket notation
            (
                "inventory.items[0].price * inventory.items[0].quantity > 500",
                {
                    "$and": [
                        {"inventory.items.0.quantity": {"$exists": True}},
                        {"inventory.items.0.price": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {
                                        "$multiply": [
                                            "$inventory.items.0.price",
                                            "$inventory.items.0.quantity",
                                        ]
                                    },
                                    500,
                                ]
                            }
                        },
                    ]
                },
            ),
            # Nested arrays with multiple indexing
            (
                "orders[0].items[1].price < orders[1].items[0].price",
                {
                    "$and": [
                        {"orders.1.items.0.price": {"$exists": True}},
                        {"orders.0.items.1.price": {"$exists": True}},
                        {
                            "$expr": {
                                "$lt": [
                                    "$orders.0.items.1.price",
                                    "$orders.1.items.0.price",
                                ]
                            }
                        },
                    ]
                },
            ),
            # Complex nested field access in expressions
            (
                "customer.orders[0].total + customer.credits > customer.limits.spending",
                {
                    "$and": [
                        {"customer.limits.spending": {"$exists": True}},
                        {"customer.credits": {"$exists": True}},
                        {"customer.orders.0.total": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {
                                        "$add": [
                                            "$customer.orders.0.total",
                                            "$customer.credits",
                                        ]
                                    },
                                    "$customer.limits.spending",
                                ]
                            }
                        },
                    ]
                },
            ),
            # Multiple level nesting with operations
            (
                "data.metrics.current / data.metrics.previous > data.thresholds.growth",
                {
                    "$and": [
                        {"data.thresholds.growth": {"$exists": True}},
                        {"data.metrics.previous": {"$exists": True}},
                        {"data.metrics.current": {"$exists": True}},
                        {
                            "$expr": {
                                "$gt": [
                                    {
                                        "$divide": [
                                            "$data.metrics.current",
                                            "$data.metrics.previous",
                                        ]
                                    },
                                    "$data.thresholds.growth",
                                ]
                            }
                        },
                    ]
                },
            ),
            # String literal keys in bracket notation
            (
                "product['sale-price'] < product['original-price'] * 0.7",
                {
                    "$and": [
                        {"product.original-price": {"$exists": True}},
                        {"product.sale-price": {"$exists": True}},
                        {
                            "$expr": {
                                "$lt": [
                                    "$product.sale-price",
                                    {"$multiply": ["$product.original-price", 0.7]},
                                ]
                            }
                        },
                    ]
                },
            ),
            # Nested field access combined with logical operators
            (
                "(user.stats.score > 100) and (user.profile.level >= 5)",
                {
                    "$and": [
                        {"user.stats.score": {"$gt": 100}},
                        {"user.profile.level": {"$gte": 5}},
                    ]
                },
            ),
        ],
    )
    def test_field_access_in_expr(self, query_str, expected_result):
        """Test field access patterns with dot notation and bracket notation in $expr queries"""
        assert are_filters_equivalent(transpile_query(query_str), expected_result)

    @pytest.mark.parametrize(
        "invalid_query",
        [
            # Binary operation outside of comparison
            "a + b",
            # Unsupported binary operator
            "a ** b > c",  # Power operator not supported
        ],
    )
    def test_invalid_expr_queries(self, invalid_query):
        """Test invalid expressions that should raise errors"""
        with pytest.raises(QueryTranspilerValueError):
            transpile_query(invalid_query)
