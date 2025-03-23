import pytest

from labtasker.server.database import DBService
from labtasker.server.embedded_db import MongoClient, ServerStore


@pytest.fixture
def persistence_path(tmpdir):
    return tmpdir / "db.json"


@pytest.fixture
def mock_db(persistence_path):
    """Create a mock database for testing."""
    store = ServerStore(persistence_path=persistence_path)
    client = MongoClient(_store=store)
    client.drop_database("test_db")
    db = DBService(client=client, db_name="test_db")
    return db
