import pytest

from labtasker.client.core.query_transpiler import transpile_query

pytestmark = [pytest.mark.unit, pytest.mark.integration]

documents = [
    {
        "idx": "doc-1",
        "args": {"foo": 0},
    },
    {
        "idx": "doc-2",
        "args": {"foo": 1, "bar": 2},
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
        [("args.foo + args.bar == 3", ["doc-2"])],
    )
    def test_arithmetic(self, query_str, expected, db_fixture):
        mongo_query = transpile_query(query_str)
        found = list(db_fixture._db.dummy.find(mongo_query))
        found_idx = set([doc["idx"] for doc in found])
        assert found_idx == set(
            expected
        ), f"{found_idx} != {set(expected)}, query: {mongo_query}"
