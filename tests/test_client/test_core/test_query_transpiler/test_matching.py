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
                        {"foo": {"$exists": True}},
                        {"bar": {"$exists": True}},
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


# class TestExprQueries:
#     """Test class for MongoDB $expr expression queries"""
#
#     def test_basic_arithmetic_operations(self):
#         """Test basic arithmetic operations in expressions"""
#         # Addition
#         assert transpile_query("a + b > c") == {
#             "$expr": {"$gt": [{"$add": ["$a", "$b"]}, "$c"]}
#         }
#
#         # Subtraction
#         assert transpile_query("price - discount < maxPrice") == {
#             "$expr": {"$lt": [{"$subtract": ["$price", "$discount"]}, "$maxPrice"]}
#         }
#
#         # Multiplication
#         assert transpile_query("quantity * price > 1000") == {
#             "$expr": {"$gt": [{"$multiply": ["$quantity", "$price"]}, 1000]}
#         }
#
#         # Division
#         assert transpile_query("total / count < 50") == {
#             "$expr": {"$lt": [{"$divide": ["$total", "$count"]}, 50]}
#         }
#
#         # Modulo
#         assert transpile_query("value % 10 == 0") == {
#             "$expr": {"$eq": [{"$mod": ["$value", 10]}, 0]}
#         }
#
#     def test_nested_operations(self):
#         """Test nested arithmetic operations with parentheses"""
#         assert transpile_query("(a + b) * c > 100") == {
#             "$expr": {"$gt": [{"$multiply": [{"$add": ["$a", "$b"]}, "$c"]}, 100]}
#         }
#
#         assert transpile_query("price + (tax * 0.1) > totalBudget") == {
#             "$expr": {
#                 "$gt": [
#                     {"$add": ["$price", {"$multiply": ["$tax", 0.1]}]},
#                     "$totalBudget",
#                 ]
#             }
#         }
#
#     def test_comparison_variations(self):
#         """Test different comparison operators with expressions"""
#         # Equal
#         assert transpile_query("a + b == c") == {
#             "$expr": {"$eq": [{"$add": ["$a", "$b"]}, "$c"]}
#         }
#
#         # Not equal
#         assert transpile_query("x + y != z") == {
#             "$expr": {"$ne": [{"$add": ["$x", "$y"]}, "$z"]}
#         }
#
#         # Greater than or equal
#         assert transpile_query("p + q >= r") == {
#             "$expr": {"$gte": [{"$add": ["$p", "$q"]}, "$r"]}
#         }
#
#         # Less than or equal
#         assert transpile_query("m + n <= o") == {
#             "$expr": {"$lte": [{"$add": ["$m", "$n"]}, "$o"]}
#         }
#
#     def test_mixed_with_constants(self):
#         """Test expressions with field names and constants"""
#         assert transpile_query("field + 10 > threshold") == {
#             "$expr": {"$gt": [{"$add": ["$field", 10]}, "$threshold"]}
#         }
#
#         assert transpile_query("price * 1.2 < maxPrice") == {
#             "$expr": {"$lt": [{"$multiply": ["$price", 1.2]}, "$maxPrice"]}
#         }
#
#     def test_multiple_operations(self):
#         """Test expressions with multiple operations"""
#         assert transpile_query("a + b * c / d > threshold") == {
#             "$expr": {
#                 "$gt": [
#                     {
#                         "$add": [
#                             "$a",
#                             {"$divide": [{"$multiply": ["$b", "$c"]}, "$d"]},
#                         ]
#                     },
#                     "$threshold",
#                 ]
#             }
#         }
#
#     def test_logical_operators(self):
#         """Test expressions combined with logical operators"""
#         assert transpile_query("a + b > c and x + y < z") == {
#             "$and": [
#                 {"$expr": {"$gt": [{"$add": ["$a", "$b"]}, "$c"]}},
#                 {"$expr": {"$lt": [{"$add": ["$x", "$y"]}, "$z"]}},
#             ]
#         }
#
#         assert transpile_query("price * quantity > budget or discount > 10") == {
#             "$or": [
#                 {"$expr": {"$gt": [{"$multiply": ["$price", "$quantity"]}, "$budget"]}},
#                 {"discount": {"$gt": 10}},
#             ]
#         }
#
#     def test_invalid_expressions(self):
#         """Test invalid expressions that should raise errors"""
#         # Binary operation outside of comparison
#         with pytest.raises(LabtaskerValueError):
#             transpile_query("a + b")
#
#         # Unsupported binary operator
#         with pytest.raises(LabtaskerValueError):
#             transpile_query("a ** b > c")  # Power operator not supported
#
#     def test_mixed_expr_and_regular_queries(self):
#         """Test mixing $expr queries with regular field queries"""
#         assert transpile_query(
#             "(price + tax > 100) and (category == 'electronics')"
#         ) == {
#             "$and": [
#                 {"$expr": {"$gt": [{"$add": ["$price", "$tax"]}, 100]}},
#                 {"category": "electronics"},
#             ]
#         }
