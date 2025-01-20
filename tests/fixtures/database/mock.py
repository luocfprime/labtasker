import pytest
from mongomock import MongoClient as MockMongoClient

from labtasker.server.database import DBService

MONGO_METHODS_TO_PATCH = [
    "find_one",
    "insert_one",
    "update_one",
    "delete_one",
    "delete_many",
    "find",
    "update_many",
    "find_one_and_update",
]


class MockSession:
    def __init__(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def start_transaction(self):
        return self

    def commit_transaction(self):
        pass

    def abort_transaction(self):
        pass


@pytest.fixture
def mock_db(monkeypatch):
    """Create a mock database for testing."""
    client = MockMongoClient()
    client.drop_database("test_db")
    db = DBService(client=client, db_name="test_db")

    # Patch MongoDB operations to ignore session parameter
    def ignore_session(original_method):
        def wrapper(*args, session=None, **kwargs):
            # Remove session parameter
            return original_method(*args, **kwargs)

        return wrapper

    for method in MONGO_METHODS_TO_PATCH:
        for collection in [db._queues, db._tasks, db._workers]:
            original = getattr(collection, method)
            monkeypatch.setattr(collection, method, ignore_session(original))

    # Patch start_session
    monkeypatch.setattr(db._client, "start_session", MockSession)

    return db
