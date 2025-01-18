import pytest
from mongomock_motor import AsyncMongoMockClient

from labtasker.server.database import AsyncDBService


class TransactionContext:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class AsyncMockSession:
    """Simple mock for MongoDB async session."""

    def start_transaction(self):
        return TransactionContext()

    async def commit_transaction(self):
        pass

    async def abort_transaction(self):
        pass


class CoroutineSession:
    def __init__(self):
        self.session = AsyncMockSession()

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    def __await__(self):
        async def coro():
            return self.session

        return coro().__await__()


async def mock_start_session(*args, **kwargs):
    """Returns an object that supports both await and async with."""

    return CoroutineSession()


@pytest.fixture
async def mock_db(monkeypatch):
    """Create a mock async database for testing."""
    client = AsyncMongoMockClient()
    client.drop_database("test_db")
    db = await AsyncDBService.init(client=client, db_name="test_db")

    # Patch MongoDB operations to ignore session parameter
    def ignore_session(original_method):
        async def wrapper(*args, session=None, **kwargs):
            return await original_method(*args, **kwargs)

        return wrapper

    # Patch collection methods to ignore session
    patched_methods = [
        "find_one",
        "insert_one",
        "update_one",
        "delete_one",
        "find",
        "update_many",
        "find_one_and_update",
    ]
    for method in patched_methods:
        for collection in [db._queues, db._tasks, db._workers]:
            original = getattr(collection, method)
            monkeypatch.setattr(collection, method, ignore_session(original))

    monkeypatch.setattr(db._client, "start_session", mock_start_session)

    return db
