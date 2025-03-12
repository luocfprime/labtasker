import pytest

from labtasker.client.core.query_transpiler import transpile_query

pytestmark = [pytest.mark.unit, pytest.mark.integration]

documents = [
    {
        "idx": "doc-1",
        "args": {
            "foo": 5,
            "bar": 10,
            "baz": 6.28,
            "text": "bad results!",
            "char": "Z",
            "flag": False,
            "nested_dict": {
                "level1_key1": 50,
                "level1_key2": {
                    "level2_key1": 100,
                    "level2_key2": {
                        "level3_key1": "shallow data",
                        "level3_key2": -42.42,
                    },
                },
            },
            "mixed_list": [
                99,
                "example",
                -3.5,
                {"inner_dict": {"key": "another_value"}},
                ["list_item1", "list_item2", 0],
            ],
            "num_list": [-5, 0, 2, 8, 10],
            "dict_list": [
                {"key1": "valueX", "key2": -1},
                {"keyA": "valueY", "keyB": 7.77},
            ],
            "boolean_values": [False, False, True],
            "complex_structure": {
                "list_in_dict": [
                    {"id": 3, "value": "cherry"},
                    {"id": 4, "value": "date"},
                ],
                "dict_in_list": [["a", "b", "c"], {"gamma": "g", "delta": "d"}],
            },
        },
    },
    {
        "idx": "doc-2",
        "args": {
            "foo": 1,
            "bar": 2,
            "baz": 3.14,
            "text": "good jobs!",
            "char": "a",
            "flag": True,
            "nested_dict": {
                "level1_key1": 10,
                "level1_key2": {
                    "level2_key1": 20,
                    "level2_key2": {"level3_key1": "deep value", "level3_key2": 99.99},
                },
            },
            "mixed_list": [
                42,
                "sample",
                7.89,
                {"inner_dict": {"key": "value"}},
                ["sublist1", "sublist2", 123],
            ],
            "num_list": [1, 2, 3, 4, 5],
            "dict_list": [{"key1": "val1", "key2": 2}, {"keyA": "valA", "keyB": 3.5}],
            "boolean_values": [True, False, True],
            "complex_structure": {
                "list_in_dict": [
                    {"id": 1, "value": "apple"},
                    {"id": 2, "value": "banana"},
                ],
                "dict_in_list": [["x", "y", "z"], {"alpha": "a", "beta": "b"}],
            },
        },
    },
]


@pytest.fixture(autouse=True)
def setup_documents(db_fixture):
    db_fixture._db.dummy.insert_many(documents)
    yield
    db_fixture._db.dummy.delete_many({})


class TestBasic:
    @pytest.mark.parametrize(
        "query_str, expected",
        [("args.foo == 5", ["doc-1"])],
    )
    def test_basic_query(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"

    @pytest.mark.parametrize(
        "query_str, expected",
        [
            ("args.foo + args.bar == 3", ["doc-2"]),
            ("args.baz * 2 == 6.28", ["doc-2"]),
            # ("args.num_list[2] - args.foo == 2", ["doc-2"]),  # MongoDB can't $subtract int from array
            # ("args.dict_list[1]['keyB'] / args.bar == 1.75", ["doc-2"]), # MongoDB $divide only supports numeric types, not array
            ("args.foo * args.bar == 2", ["doc-2"]),
            ("args.baz / args.bar == 1.57", ["doc-2"]),
            # ("args.num_list[1] + args.num_list[3] == 6", ["doc-2"]), # MongoDB $add only supports numeric or date types, not array
        ],
    )
    def test_arithmetic(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"

    @pytest.mark.parametrize(
        "query_str, expected",
        [
            # text matching
            (r"args.text == 'good jobs!'", ["doc-2"]),
            (r"args.char == 'a'", ["doc-2"]),
            # bool matching
            (r"args.flag == True", ["doc-2"]),
            # integer matching
            (r"args.foo == 1", ["doc-2"]),
            (r"args.bar == 2", ["doc-2"]),
            # float matching
            (r"args.baz == 3.14", ["doc-2"]),
            # dict matching
            (r"args.nested_dict['level1_key1'] == 10", ["doc-2"]),
            (r"args.nested_dict['level1_key2']['level2_key1'] == 20", ["doc-2"]),
            (
                r"args.nested_dict['level1_key2']['level2_key2']['level3_key1'] == 'deep value'",
                ["doc-2"],
            ),
            (
                r"args.nested_dict['level1_key2']['level2_key2']['level3_key2'] == 99.99",
                ["doc-2"],
            ),
            # list element matching
            (r"args.mixed_list[0] == 42", ["doc-2"]),
            (r"args.mixed_list[1] == 'sample'", ["doc-2"]),
            (r"args.mixed_list[2] == 7.89", ["doc-2"]),
            (r"args.num_list[0] == 1", ["doc-2"]),
            (r"args.num_list[4] == 5", ["doc-2"]),
            # list in dict matching
            (r"args.dict_list[0]['key1'] == 'val1'", ["doc-2"]),
            (r"args.dict_list[1]['keyB'] == 3.5", ["doc-2"]),
            # bool list matching
            (r"args.boolean_values[0] == True", ["doc-2"]),
            (r"args.boolean_values[1] == False", ["doc-1", "doc-2"]),
            # complex structure matching
            (
                r"args.complex_structure['list_in_dict'][0]['value'] == 'apple'",
                ["doc-2"],
            ),
            (r"args.complex_structure['dict_in_list'][1]['alpha'] == 'a'", ["doc-2"]),
            (r"args.boolean_values[0] == True", ["doc-2"]),
            (r"args.nested_dict['level1_key1'] == 10", ["doc-2"]),
            (r"args.mixed_list[0] == 42", ["doc-2"]),
            (r"args.foo == 1 and args.bar == 2", ["doc-2"]),
            # (r"args.num_list[-1] == 5", ["doc-2"]),  # (negative indexing not supported)
            (
                r"args.nested_dict['level1_key1'] > 5 and 15 > args.nested_dict['level1_key1']",
                ["doc-2"],
            ),
            (r"args.foo < 0", []),
            (r"args.foo == 1 and args.bar == 2", ["doc-2"]),
            (r"args.foo == 1 or args.bar == 99", ["doc-2"]),
            (r"args.foo == 1 and args.bar == 2 and args.baz > 3", ["doc-2"]),
            (
                r"args.nested_dict.level1_key1 == 10 and args.nested_dict.level1_key2.level2_key1 == 20",
                ["doc-2"],
            ),
            (r"args.complex_structure.list_in_dict[0].value == 'apple'", ["doc-2"]),
            (r"args.flag == True", ["doc-2"]),
            (
                r"args.boolean_values[0] == True and args.boolean_values[1] == False",
                ["doc-2"],
            ),
        ],
    )
    def test_simple_matching(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"

    @pytest.mark.parametrize(
        "query_str, expected",
        [
            (r"regex(args.text, '^good .*') and args.char == 'A'", []),
            (r"regex(args.text, '.*jobs!$') or args.foo == 99", ["doc-2"]),
            (
                r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, 'deep.*')",
                ["doc-2"],
            ),
            (r"regex(args.mixed_list[1], 'sample')", ["doc-2"]),
            (r"regex(args.text, '^good .*')", ["doc-2"]),
            (r"regex(args.text, '^bad .*')", ["doc-1"]),
            (r"regex(args.text, '.*jobs!$')", ["doc-2"]),
            (r"regex(args.text, '.*work!$')", []),
            (r"regex(args.char, '^[A-Z]$')", ["doc-1"]),
            (r"regex(args.char, '^[a-z]$')", ["doc-2"]),
            (r"regex(args.text, 'GOOD JOBS!')", []),
            (r"regex(args.text, '(?i)GOOD JOBS!')", ["doc-2"]),
            (
                r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^deep.*')",
                ["doc-2"],
            ),
            (
                r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^shallow.*')",
                ["doc-1"],
            ),
            (r"regex(args.text, '.*good.*')", ["doc-2"]),
            (r"regex(args.text, '.*bad.*')", ["doc-1"]),
            (r"regex(args.text, r'.*\!$')", ["doc-1", "doc-2"]),
            (r"regex(args.text, r'.*\?$')", []),
            (r"regex(args.mixed_list[1], 'sample')", ["doc-2"]),
            (r"regex(args.mixed_list[1], '^SAMPLE$')", []),
            (r"regex(args.mixed_list[1], '(?i)^SAMPLE$')", ["doc-2"]),
            (
                r"regex(args.complex_structure.list_in_dict[0].value, 'apple')",
                ["doc-2"],
            ),
            (r"regex(args.complex_structure.list_in_dict[0].value, 'banana')", []),
            (
                r"regex(args.text, '^good .*') or regex(args.char, '^[A-Z]$')",
                ["doc-1", "doc-2"],
            ),
            (
                r"regex(args.text, '^bad .*') or regex(args.char, '^[a-z]$')",
                ["doc-1", "doc-2"],
            ),
            (
                r"regex(args.text, '^good .*') and regex(args.char, '^[A-Z]$')",
                [],
            ),
            (
                r"regex(args.text, '^good .*') and regex(args.char, '^[a-z]$')",
                ["doc-2"],
            ),
            (r"regex(args.non_existent_key, '.*')", []),
            (r"regex(args.dict_list[1].keyA, 'valA')", ["doc-2"]),
            (r"regex(args.dict_list[1].keyA, 'valB')", []),
            (r"regex(args.dict_list[1].keyA, 'value.*')", ["doc-1"]),
        ],
    )
    def test_regex_matching(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"

    @pytest.mark.parametrize(
        "query_str, expected",
        [
            (r"exists(args.text)", ["doc-1", "doc-2"]),
            (r"exists(args.non_existent_key)", []),
            (r"exists(args.nested_dict.level1_key1)", ["doc-1", "doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key1)", ["doc-1", "doc-2"]),
            (
                r"exists(args.nested_dict.level1_key2.level2_key2.level3_key1)",
                ["doc-1", "doc-2"],
            ),
            (r"exists(args.nested_dict.level1_key2.level2_key2.level3_key3)", []),
            (r"exists(args.mixed_list)", ["doc-1", "doc-2"]),
            (r"exists(args.mixed_list[0])", ["doc-1", "doc-2"]),
            (r"exists(args.mixed_list[10])", []),
            (r"exists(args.dict_list[1].keyA)", ["doc-1", "doc-2"]),
            (r"exists(args.dict_list[1].keyC)", []),
            (r"exists(args.num_list[4])", ["doc-1", "doc-2"]),
            (r"exists(args.num_list[10])", []),
            (r"exists(args.complex_structure.list_in_dict)", ["doc-1", "doc-2"]),
            (
                r"exists(args.complex_structure.list_in_dict[0].value)",
                ["doc-1", "doc-2"],
            ),
            (r"exists(args.complex_structure.list_in_dict[2])", []),
            (r"exists(args.boolean_values[2])", ["doc-1", "doc-2"]),
            (r"exists(args.boolean_values[3])", []),
            (r"exists(args.non_existent_key, False)", ["doc-1", "doc-2"]),
            (r"exists(args.foo, False)", []),
            (r"exists(args.nested_dict.level1_key2, False)", []),
            (
                r"exists(args.nested_dict.level1_key2.level2_key3, False)",
                ["doc-1", "doc-2"],
            ),
            (r"exists(args.mixed_list[1], False)", []),
            (r"exists(args.mixed_list[5], False)", ["doc-1", "doc-2"]),
            (r"exists(args.dict_list[0].key1, False)", []),
            (r"exists(args.dict_list[0].key3, False)", ["doc-1", "doc-2"]),
            (r"regex(args.text, '^good .*')", ["doc-2"]),
            (r"regex(args.char, '^[A-Z]$')", ["doc-1"]),
            (
                r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, 'deep.*')",
                ["doc-2"],
            ),
            (r"regex(args.text, 'bad .*')", ["doc-1"]),
            (r"regex(args.text, '.*jobs!$')", ["doc-2"]),
            (r"regex(args.text, '.*wrong$')", []),
            (r"exists(args.text) and regex(args.text, '^good .*')", ["doc-2"]),
            (r"exists(args.text) and regex(args.text, 'bad .*')", ["doc-1"]),
            (
                r"exists(args.non_existent_key) or regex(args.text, '^good .*')",
                ["doc-2"],
            ),
            (
                r"exists(args.nested_dict.level1_key2.level2_key2.level3_key1) and regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^deep')",
                ["doc-2"],
            ),
            (
                r"exists(args.nested_dict.level1_key2.level2_key2.level3_key1) and regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^shallow')",
                ["doc-1"],
            ),
            (
                r"exists(args.dict_list[0].key1) and exists(args.dict_list[1].keyA)",
                ["doc-1", "doc-2"],
            ),
            (r"exists(args.dict_list[0].key1) and exists(args.dict_list[1].keyC)", []),
            (
                r"exists(args.dict_list[0].key1) or exists(args.dict_list[1].keyC)",
                ["doc-1", "doc-2"],
            ),
            (r"exists(args.boolean_values[2])", ["doc-1", "doc-2"]),
            (r"exists(args.boolean_values[3])", []),
            (r"exists(args.non_existent_key, False)", ["doc-1", "doc-2"]),
            (r"exists(args.foo, False)", []),
            (r"exists(args.nested_dict.level1_key2, False)", []),
            (
                r"exists(args.nested_dict.level1_key2.level2_key3, False)",
                ["doc-1", "doc-2"],
            ),
        ],
    )
    def test_multi_mixed_matching(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"

    @pytest.mark.parametrize(
        "query_str, expected",
        [
            ("args.foo + args.bar == 15", ["doc-1"]),
            # 5 * 6.28 ≈ 31.4
            ("args.foo * args.baz > 31.39 and args.foo * args.baz < 31.41", ["doc-1"]),
            ("args.bar - args.foo == 5", ["doc-1"]),
            # 6.28 / 5 ≈ 1.256
            (
                "args.baz / args.foo > 1.2559 and args.baz / args.foo < 1.2561",
                ["doc-1"],
            ),
            ("args.foo == 1 and args.bar == 2", ["doc-2"]),
            ("args.foo == 5 or args.bar == 99", ["doc-1"]),
            # 6.28 > 6
            ("args.foo == 5 and args.bar == 10 and args.baz > 6.27", ["doc-1"]),
            ("args.foo > 3 and args.bar < 15", ["doc-1"]),
            ("args.num_list[0] < 0 and args.num_list[1] == 0", ["doc-1"]),
            # ("args.num_list[4] / args.num_list[2] > 4.99 and args.num_list[4] / args.num_list[2] < 5.01", ["doc-1"]),  # MongoDB $divide only supports numeric types, not array
            (
                "args.boolean_values[2] == True and args.boolean_values[1] == False",
                ["doc-1", "doc-2"],
            ),
            # 7.77 > 7
            (
                "args.dict_list[1].keyB > 7.76 and args.dict_list[1].keyB < 7.78",
                ["doc-1"],
            ),
            ("regex(args.text, '^bad .*')", ["doc-1"]),
            ("regex(args.char, '^[A-Z]$')", ["doc-1"]),
            (
                "regex(args.nested_dict.level1_key2.level2_key2.level3_key1, 'shallow.*')",
                ["doc-1"],
            ),
            ("regex(args.dict_list[1].keyA, 'value.*')", ["doc-1"]),
            ("regex(args.mixed_list[1], '.*ample')", ["doc-1", "doc-2"]),
            ("exists(args.text)", ["doc-1", "doc-2"]),
            ("exists(args.unknown_field)", []),
            ("exists(args.mixed_list[3].inner_dict.key)", ["doc-1", "doc-2"]),
            (
                "exists(args.nested_dict.level1_key2.level2_key2.level3_key1)",
                ["doc-1", "doc-2"],
            ),
            ("exists(args.mixed_list[4][2])", ["doc-1", "doc-2"]),
            ("exists(args.mixed_list[4][99])", []),
            (
                "args.nested_dict.level1_key2.level2_key1 + args.nested_dict.level1_key1 == 150",
                ["doc-1"],
            ),
            ("args.mixed_list[0] > 50 or args.dict_list[0].key2 < 0", ["doc-1"]),
            # ("args.num_list[2] * args.num_list[3] > 15.99 and args.num_list[2] * args.num_list[3] < 16.01", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            ("args.dict_list[0].key2 < 0 and args.dict_list[1].keyB > 7.76", ["doc-1"]),
            ("args.foo == 5 and args.bar == 10", ["doc-1"]),
            ("args.foo == 1 or args.bar == 10", ["doc-1", "doc-2"]),
            ("args.baz > 6.27 and args.foo < 10", ["doc-1"]),
            (
                "args.nested_dict.level1_key1 == 50 and args.nested_dict.level1_key2.level2_key1 == 100",
                ["doc-1"],
            ),
            ("args.mixed_list[0] == 99", ["doc-1"]),
            ("args.mixed_list[1] == 'example'", ["doc-1"]),
            # -3.5 floating point
            ("args.mixed_list[2] > -3.51 and args.mixed_list[2] < -3.49", ["doc-1"]),
            ("args.num_list[0] == -5", ["doc-1"]),
            ("args.dict_list[0].key1 == 'valueX'", ["doc-1"]),
            # 7.77 floating point
            (
                "args.dict_list[1].keyB > 7.76 and args.dict_list[1].keyB < 7.78",
                ["doc-1"],
            ),
            ("args.boolean_values[0] == False", ["doc-1"]),
            ("args.complex_structure.list_in_dict[0].value == 'cherry'", ["doc-1"]),
            ("args.complex_structure.dict_in_list[1].gamma == 'g'", ["doc-1"]),
            # New test cases for negative number handling
            # ("-5 + args.num_list[0] == -10", ["doc-1"]),  # MongoDB $add only supports numeric types, not array
            # ("args.num_list[0] * (-1) == 5", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # ("args.num_list[0] / (-1) == 5", ["doc-1"]),  # MongoDB $divide only supports numeric types, not array
            # ("args.num_list[0] - (-3) == -2", ["doc-1"]),  # MongoDB $subtract only supports numeric types, not array
            # ("args.dict_list[0].key2 * (-2) == 2", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # ("args.mixed_list[2] * (-2) > 6.99 and -2 * args.mixed_list[2] < 7.01", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            (
                "args.nested_dict.level1_key2.level2_key2.level3_key2 < -42.41 and args.nested_dict.level1_key2.level2_key2.level3_key2 > -42.43",
                ["doc-1"],
            ),  # -42.42
            ("args.num_list[0] < -4.99 and args.num_list[0] > -5.01", ["doc-1"]),  # -5
            ("args.dict_list[0].key2 == -1", ["doc-1"]),  # exact -1
            ("args.mixed_list[2] == -3.5", ["doc-1"]),  # exact -3.5
            # ("args.num_list[0] + args.mixed_list[2] < -8.49 and args.num_list[0] + args.mixed_list[2] > -8.51", ["doc-1"]),  # MongoDB $add only supports numeric types, not array
            # ("args.num_list[0] * args.dict_list[0].key2 == 5", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # New test cases for negative field references
            ("-args.foo == -5", ["doc-1"]),  # negating field value
            ("-args.bar == -10", ["doc-1"]),  # negating integer field
            (
                "-args.baz > -6.29 and -args.baz < -6.27",
                ["doc-1"],
            ),  # negating float field with range
            # ("-args.num_list[0] == 5", ["doc-1"]),  # MongoDB arithmetic operators only support numeric types, not array
            # ("-args.dict_list[0].key2 == 1", ["doc-1"]),  # MongoDB arithmetic operators only support numeric types, not array
            # ("-args.mixed_list[2] > 3.49 and -args.mixed_list[2] < 3.51", ["doc-1"]),  # MongoDB arithmetic operators only support numeric types, not array
            (
                "-args.nested_dict.level1_key2.level2_key2.level3_key2 > 42.41 and -args.nested_dict.level1_key2.level2_key2.level3_key2 < 42.43",
                ["doc-1"],
            ),  # negating deeply nested negative
            (
                "args.foo + (-args.bar) == -5",
                ["doc-1"],
            ),  # arithmetic with negated field
            # ("args.foo * (-args.bar) == -50", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # ("-args.num_list[0] + (-args.mixed_list[2]) == 8.5", ["doc-1"]),  # MongoDB $add only supports numeric types, not array
            # ("-args.foo * args.bar == -50", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # ("-args.dict_list[0].key2 + args.mixed_list[2] == -2.5", ["doc-1"]),  # MongoDB $add only supports numeric types, not array
            # ("-args.foo == args.num_list[0]", ["doc-1"]),  # MongoDB arithmetic operators only support numeric types, not array
            (
                "(-args.bar) / 2 == -5",
                ["doc-1"],
            ),  # parenthesized negation in arithmetic
            (
                "-args.nested_dict.level1_key1 == -50",
                ["doc-1"],
            ),  # negating nested field
            (
                "-args.nested_dict.level1_key2.level2_key1 == -100",
                ["doc-1"],
            ),  # negating deeply nested field
            # New test cases for negating expressions
            ("-(args.foo + args.bar) == -15", ["doc-1"]),  # negating sum
            ("-(args.bar - args.foo) == -5", ["doc-1"]),  # negating difference
            # ("-(args.foo * args.baz) > -31.41 and -(args.foo * args.baz) < -31.39", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            (
                "-(args.baz / args.foo) > -1.2561 and -(args.baz / args.foo) < -1.2559",
                ["doc-1"],
            ),  # negating division with range
            # ("-(args.num_list[0] + args.mixed_list[2]) > 8.49 and -(args.num_list[0] + args.mixed_list[2]) < 8.51", ["doc-1"]),  # MongoDB $add only supports numeric types, not array
            (
                "-(args.nested_dict.level1_key2.level2_key1 + args.nested_dict.level1_key1) == -150",
                ["doc-1"],
            ),  # negating sum of nested fields
            # ("-(args.num_list[4] / args.num_list[2]) > -5.01 and -(args.num_list[4] / args.num_list[2]) < -4.99", ["doc-1"]),  # MongoDB $divide only supports numeric types, not array
            # ("-(args.dict_list[0].key2 * args.num_list[0]) == -5", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            (
                "-(args.foo + args.bar) + args.baz > -8.73 and -(args.foo + args.bar) + args.baz < -8.71",
                ["doc-1"],
            ),  # complex with negated expression
            # ("-(args.num_list[2] * args.num_list[3]) > -16.01 and -(args.num_list[2] * args.num_list[3]) < -15.99", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # ("-(args.mixed_list[0] - args.mixed_list[2]) > -102.51 and -(args.mixed_list[0] - args.mixed_list[2]) < -102.49", ["doc-1"]),  # MongoDB arithmetic operators only support numeric types, not array
            # ("-(args.foo * 2 + args.bar) == -20", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # ("-(args.nested_dict.level1_key1) * 2 == -100", ["doc-1"]),  # MongoDB $multiply only supports numeric types, not array
            # ("-args.num_list[0] - args.dict_list[0].key2 == 6", ["doc-1"]),  # MongoDB arithmetic operators only support numeric types, not array
            # ("-(args.mixed_list[2] - args.num_list[0]) == -1.5", ["doc-1"]),  # MongoDB arithmetic operators only support numeric types, not array
        ],
    )
    def test_multi_document_matching(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"
