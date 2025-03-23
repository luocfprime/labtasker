import mongomock
import pytest

from labtasker.server.embedded_db import ServerStore
from labtasker.utils import get_current_time

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def dummy_collection(db_fixture):
    db_fixture._db.create_collection("dummy")
    yield db_fixture._db.dummy
    db_fixture._db.drop_collection("dummy")


def test_dump_and_load(db_fixture, dummy_collection, persistence_path):
    t = get_current_time()
    dummy_collection.insert_one({"foo": "bar", "t": t})

    dummy_collection.insert_one({"gaz": "baz", "bool": False})
    dummy_collection.update_one({"gaz": "baz"}, {"$set": {"bool": True}})

    dummy_collection.insert_one({"to-be-deleted": "baz"})
    dummy_collection.delete_one({"to-be-deleted": "baz"})

    server_store = db_fixture._client._store
    server_store.save_to_disk()

    new_client = mongomock.MongoClient(
        _store=ServerStore(persistence_path=persistence_path)
    )
    new_dummy_collection = new_client["test_db"].dummy

    assert new_dummy_collection.count_documents({}) == 2
    # only compare to seconds, as microseconds may lose precision
    assert new_dummy_collection.find_one({"foo": "bar"})["t"].replace(
        microsecond=0
    ) == t.replace(microsecond=0)
    assert new_dummy_collection.find_one({"gaz": "baz"})["bool"] is True
    assert new_dummy_collection.find_one({"to-be-deleted": "baz"}) is None
