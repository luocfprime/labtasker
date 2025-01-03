import os
from datetime import datetime, timezone

import pytest
from mongomock import MongoClient

from labtasker.config import ServerConfig
from labtasker.database import DatabaseClient


@pytest.fixture
def mock_db(monkeypatch):
    """Create a mock database for testing."""
    client = MongoClient()
    db = DatabaseClient(client=client, db_name="test_db")

    # Clear any existing data
    client.drop_database("test_db")

    # Create indexes
    db.queues.create_index("queue_name", unique=True)
    db.tasks.create_index([("queue_name", 1), ("status", 1)])

    # Only pre-populate for specific tests that need it
    if os.environ.get("PREPOPULATE_TEST_DATA"):
        # Pre-populate test data
        db.queues.insert_one(
            {
                "_id": "test_queue_id",
                "queue_name": "test_queue",
                "password": db.security.hash_password("test_password"),
                "created_at": datetime.now(timezone.utc),
            }
        )

        db.tasks.insert_one(
            {
                "_id": "test_task_id",
                "queue_id": "test_queue_id",
                "queue_name": "test_queue",
                "task_name": "test_task",
                "status": "created",
                "args": {"param1": 1},
                "metadata": {"tags": ["test_tag"]},
                "created_at": datetime.now(timezone.utc),
            }
        )

    yield db


@pytest.fixture
def test_config(monkeypatch):
    """Set test environment variables."""
    monkeypatch.setenv("DB_NAME", "test_db")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "27017")
    monkeypatch.setenv("ADMIN_USERNAME", "test_admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "test_password")
    return ServerConfig()


@pytest.fixture
def queue_data():
    """Sample queue data for testing."""
    return {"queue_name": "test_queue", "password": "test_password"}


@pytest.fixture
def task_data():
    """Sample task data for testing."""
    return {
        "queue_name": "test_queue",
        "task_name": "test_task",
        "args": {"param1": 1},
        "metadata": {"tag": "test"},
    }
