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
                        "level3_key2": -42.42
                    }
                }
            },
            "mixed_list": [
                99,
                "example",
                -3.5,
                {"inner_dict": {"key": "another_value"}},
                ["list_item1", "list_item2", 0]
            ],
            "num_list": [-5, 0, 2, 8, 10],
            "dict_list": [
                {"key1": "valueX", "key2": -1},
                {"keyA": "valueY", "keyB": 7.77}
            ],
            "boolean_values": [False, False, True],
            "complex_structure": {
                "list_in_dict": [
                    {"id": 3, "value": "cherry"},
                    {"id": 4, "value": "date"}
                ],
                "dict_in_list": [
                    ["a", "b", "c"],
                    {"gamma": "g", "delta": "d"}
                ]
            }
        }
    },
    {
        "idx": "doc-2",
        "args": {
            "foo": 1,
            "bar": 2,
            "baz": 3.14,
            "text": "good jobs!",
            "char": "A",
            "flag": True,
            "nested_dict": {
              "level1_key1": 10,
              "level1_key2": {
                "level2_key1": 20,
                "level2_key2": {
                  "level3_key1": "deep value",
                  "level3_key2": 99.99
                }
              }
            },
            "mixed_list": [
              42,
              "sample",
              7.89,
              {"inner_dict": {"key": "value"}},
              ["sublist1", "sublist2", 123]
            ],
            "num_list": [1, 2, 3, 4, 5],
            "dict_list": [
              {"key1": "val1", "key2": 2},
              {"keyA": "valA", "keyB": 3.5}
            ],
            "boolean_values": [True, False, True],
            "complex_structure": {
              "list_in_dict": [
                {"id": 1, "value": "apple"},
                {"id": 2, "value": "banana"}
              ],
              "dict_in_list": [
                ["x", "y", "z"],
                {"alpha": "a", "beta": "b"}
              ]
            }
          }
    },
]


@pytest.fixture(autouse=True)
def setup_documents(db_fixture):
    db_fixture._db.dummy.insert_many(documents)


class TestBasic:
    @pytest.mark.parametrize(
        "query_str, expected",
        [("args.foo == 0", ["doc-1"])],
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
            ("args.num_list[2] - args.foo == 2", ["doc-2"]),
            ("args.dict_list[1]['keyB'] / args.bar == 1.75", ["doc-2"]),
            ("args.foo * args.bar == 2", ["doc-2"]),
            ("args.baz / args.bar == 1.57", ["doc-2"]),
            ("args.num_list[1] + args.num_list[3] == 6", ["doc-2"]),
            # ("args.boolean_values.count(True) == 2", ["doc-2"]) # not supported ".count"
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
            (r"args.char == 'A'", ["doc-2"]),

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
            (r"args.nested_dict['level1_key2']['level2_key2']['level3_key1'] == 'deep value'", ["doc-2"]),
            (r"args.nested_dict['level1_key2']['level2_key2']['level3_key2'] == 99.99", ["doc-2"]),

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
            (r"args.boolean_values[1] == False", ["doc-2"]),

            # complex structure matching
            (r"args.complex_structure['list_in_dict'][0]['value'] == 'apple'", ["doc-2"]),
            (r"args.complex_structure['dict_in_list'][1]['alpha'] == 'a'", ["doc-2"]),

            (r"args.boolean_values[0] == True", ["doc-2"]),
            (r"args.nested_dict['level1_key1'] == 10", ["doc-2"]),
            (r"args.mixed_list[0] == 42", ["doc-2"]),
            (r"args.foo == 1 and args.bar == 2", ["doc-2"]),
            (r"args.num_list[-1] == 5", ["doc-2"]),
            (r"args.nested_dict['level1_key1'] > 5 and 15 > args.nested_dict['level1_key1']", ["doc-2"]),
            (r"args.foo < 0", []),
            (r"args.foo == 1 and args.bar == 2", ["doc-2"]),
            (r"args.foo == 1 or args.bar == 99", ["doc-2"]),
            (r"args.foo == 1 and args.bar == 2 and args.baz > 3", ["doc-2"]),

            (r"args.nested_dict.level1_key1 == 10 and args.nested_dict.level1_key2.level2_key1 == 20", ["doc-2"]),
            (r"args.complex_structure.list_in_dict[0].value == 'apple'", ["doc-2"]),
            (r"args.flag == True", ["doc-2"]),
            (r"args.boolean_values[0] == True and args.boolean_values[1] == False", ["doc-2"]),
        ]
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
            (r"regex(args.text, '^good .*') and args.char == 'A'", ["doc-2"]),
            (r"regex(args.text, '.*jobs!$') or args.foo == 99", ["doc-2"]),
            (r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, 'deep.*')", ["doc-2"]),
            (r"regex(args.mixed_list[1], 'sample')", ["doc-2"]),
            (r"regex(args.text, '^good .*')", ["doc-2"]),
            (r"regex(args.text, '^bad .*')", []),
            (r"regex(args.text, '.*jobs!$')", ["doc-2"]),
            (r"regex(args.text, '.*work!$')", []),
            (r"regex(args.char, '^[A-Z]$')", ["doc-2"]),
            (r"regex(args.char, '^[a-z]$')", []),
            (r"regex(args.text, 'GOOD JOBS!')", []),
            (r"regex(args.text, '(?i)GOOD JOBS!')", ["doc-2"]),
            (r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^deep.*')", ["doc-2"]),
            (r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^shallow.*')", []),
            (r"regex(args.text, '.*good.*')", ["doc-2"]),
            (r"regex(args.text, '.*bad.*')", []),
            (r"regex(args.text, '.*\!$')", ["doc-2"]),
            (r"regex(args.text, '.*\?$')", []),
            (r"regex(args.foo, '^\d+$')", ["doc-2"]),
            (r"regex(args.baz, '^\d+\.\d+$')", ["doc-2"]),
            (r"regex(args.baz, '^\d+$')", []),
            (r"regex(args.mixed_list[1], 'sample')", ["doc-2"]),
            (r"regex(args.mixed_list[1], '^SAMPLE$')", []),
            (r"regex(args.mixed_list[1], '(?i)^SAMPLE$')", ["doc-2"]),
            (r"regex(args.complex_structure.list_in_dict[0].value, 'apple')", ["doc-2"]),
            (r"regex(args.complex_structure.list_in_dict[0].value, 'banana')", []),
            (r"regex(args.text, '^good .*') or regex(args.char, '^[A-Z]$')", ["doc-2"]),
            (r"regex(args.text, '^bad .*') or regex(args.char, '^[a-z]$')", []),
            (r"regex(args.text, '^good .*') and regex(args.char, '^[A-Z]$')", ["doc-2"]),
            (r"regex(args.text, '^good .*') and regex(args.char, '^[a-z]$')", []),
            (r"regex(args.non_existent_key, '.*')", []),
            (r"regex(args.dict_list[1].keyA, 'valA')", ["doc-2"]),
            (r"regex(args.dict_list[1].keyA, 'valB')", []),
            (r"regex(args.num_list[2], '^3$')", ["doc-2"]),
            (r"regex(args.num_list[2], '^4$')", []),
            (r"regex(args.flag, True)", ["doc-2"]),
            (r"regex(args.flag, False)", []),
        ]
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
            (r"exists(args.text)", ["doc-2"]),
            (r"exists(args.non_existent_key)", []),
            (r"exists(args.nested_dict.level1_key1)", ["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key1)", ["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key2.level3_key1)", ["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key2.level3_key3)", []),
            (r"exists(args.mixed_list)", ["doc-2"]),
            (r"exists(args.mixed_list[0])", ["doc-2"]),
            (r"exists(args.mixed_list[10])", []),
            (r"exists(args.dict_list[1].keyA)", ["doc-2"]),
            (r"exists(args.dict_list[1].keyC)", []),
            (r"exists(args.num_list[4])", ["doc-2"]),
            (r"exists(args.num_list[10])", []),
            (r"exists(args.complex_structure.list_in_dict)", ["doc-2"]),
            (r"exists(args.complex_structure.list_in_dict[0].value)", ["doc-2"]),
            (r"exists(args.complex_structure.list_in_dict[2])", []),
            (r"exists(args.boolean_values[0])", ["doc-2"]),
            (r"exists(args.boolean_values[3])", []),
            (r"exists(args.non_existent_key, False)", ["doc-2"]),
            (r"exists(args.foo, False)", []),
            (r"exists(args.nested_dict.level1_key2, False)", []),
            (r"exists(args.nested_dict.level1_key2.level2_key3, False)", ["doc-2"]),
            (r"exists(args.mixed_list[1], False)", []),
            (r"exists(args.mixed_list[5], False)", ["doc-2"]),
            (r"exists(args.dict_list[0].key1, False)", []),
            (r"exists(args.dict_list[0].key3, False)", ["doc-2"]),
        ]
    )
    def test_exists_mathing(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"


    @pytest.mark.parametrize(
        "query_str, expected",
        [
            (r"exists(args.text)", ["doc-2"]),
            (r"exists(args.non_existent_key)", []),
            (r"exists(args.nested_dict.level1_key1)", ["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key1)", ["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key2.level3_key1)", ["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key2.level3_key3)", []),

            (r"exists(args.mixed_list)", ["doc-2"]),
            (r"exists(args.mixed_list[0])", ["doc-2"]),
            (r"exists(args.mixed_list[10])", []),
            (r"exists(args.dict_list[1].keyA)", ["doc-2"]),
            (r"exists(args.dict_list[1].keyC)", []),
            (r"exists(args.num_list[4])", ["doc-2"]),
            (r"exists(args.num_list[10])", []),
            (r"exists(args.complex_structure.list_in_dict[1].value)", ["doc-2"]),
            (r"exists(args.complex_structure.list_in_dict[2])", []),

            (r"regex(args.text, '^good .*')", ["doc-2"]),
            (r"regex(args.char, '^[A-Z]$')", ["doc-2"]),
            (r"regex(args.nested_dict.level1_key2.level2_key2.level3_key1, 'deep.*')", ["doc-2"]),
            (r"regex(args.text, 'bad .*')", []),
            (r"regex(args.text, '.*jobs!$')", ["doc-2"]),
            (r"regex(args.text, '.*wrong$')", []),

            (r"exists(args.text) and regex(args.text, '^good .*')", ["doc-2"]),
            (r"exists(args.text) and regex(args.text, 'bad .*')", []),
            (r"exists(args.non_existent_key) or regex(args.text, '^good .*')", ["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key2.level3_key1) and regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^deep')",["doc-2"]),
            (r"exists(args.nested_dict.level1_key2.level2_key2.level3_key1) and regex(args.nested_dict.level1_key2.level2_key2.level3_key1, '^shallow')",[]),
            (r"exists(args.dict_list[0].key1) and exists(args.dict_list[1].keyA)", ["doc-2"]),
            (r"exists(args.dict_list[0].key1) and exists(args.dict_list[1].keyC)", []),
            (r"exists(args.dict_list[0].key1) or exists(args.dict_list[1].keyC)", ["doc-2"]),

            (r"exists(args.boolean_values[2])", ["doc-2"]),
            (r"exists(args.boolean_values[3])", []),
            (r"exists(args.non_existent_key, False)", ["doc-2"]),
            (r"exists(args.foo, False)", []),
            (r"exists(args.nested_dict.level1_key2, False)", []),
            (r"exists(args.nested_dict.level1_key2.level2_key3, False)", ["doc-2"]),
        ]
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
            ("args.foo * args.baz == 31.4", ["doc-1"]),
            ("args.bar - args.foo == 5", ["doc-1"]),
            ("args.baz / args.foo == 1.256", ["doc-1"]),
            ("args.foo == 1 and args.bar == 2", ["doc-2"]),
            ("args.foo == 5 or args.bar == 99", ["doc-1"]),
            ("args.foo == 5 and args.bar == 10 and args.baz > 6", ["doc-1"]),

            ("args.foo > 3 and args.bar < 15", ["doc-1"]),
            ("args.num_list[0] < 0 and args.num_list[1] == 0", ["doc-1"]),
            ("args.num_list[4] / args.num_list[2] == 5", ["doc-1"]),
            ("args.boolean_values[2] == True and args.boolean_values[1] == False", ["doc-1"]),
            ("args.dict_list[1].keyB > 7", ["doc-1"]),

            ("regex(args.text, '^bad .*')", ["doc-1"]),
            ("regex(args.char, '^[A-Z]$')", ["doc-1"]),
            ("regex(args.nested_dict.level1_key2.level2_key2.level3_key1, 'shallow.*')", ["doc-1"]),
            ("regex(args.dict_list[1].keyA, 'value.*')", ["doc-1"]),
            ("regex(args.mixed_list[1], '.*ample')", ["doc-1"]),

            ("exists(args.text)", ["doc-1", "doc-2"]),
            ("exists(args.unknown_field)", []),
            ("exists(args.mixed_list[3].inner_dict.key)", ["doc-1"]),
            ("exists(args.nested_dict.level1_key2.level2_key2.level3_key1)", ["doc-1", "doc-2"]),
            ("exists(args.mixed_list[4][2])", ["doc-1"]),
            ("exists(args.mixed_list[4][99])", []),

            ("args.nested_dict.level1_key2.level2_key1 + args.nested_dict.level1_key1 == 150", ["doc-1"]),
            ("args.mixed_list[0] > 50 or args.dict_list[0].key2 < 0", ["doc-1"]),
            ("args.num_list[2] * args.num_list[3] == 16", ["doc-1"]),
            ("args.dict_list[0].key2 < 0 and args.dict_list[1].keyB > 7", ["doc-1"]),
        ]
    )
    def test_multi_document_matching(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"
