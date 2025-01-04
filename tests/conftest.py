import os
from datetime import datetime, timedelta, timezone

import pytest
from mongomock import MongoClient

from labtasker.config import ServerConfig
from labtasker.database import DatabaseClient


class TimeControl:
    """Helper class for controlling time in tests."""

    def __init__(self, current_time: datetime):
        self._current_time = current_time

    @property
    def current_time(self) -> datetime:
        return self._current_time

    def time_travel(self, seconds: int) -> datetime:
        self._current_time += timedelta(seconds=seconds)
        return self._current_time


@pytest.fixture
def mock_datetime(monkeypatch):
    """Fixture to mock datetime with controllable current time."""
    from datetime import datetime, timezone

    from labtasker import utils

    # Start with a fixed time to make tests deterministic
    time_control = TimeControl(
        current_time=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    )

    # Patch get_current_time in all modules that use it
    def mock_get_current_time():
        return time_control.current_time

    monkeypatch.setattr("labtasker.utils.get_current_time", mock_get_current_time)
    monkeypatch.setattr("labtasker.database.get_current_time", mock_get_current_time)
    monkeypatch.setattr("labtasker.server.get_current_time", mock_get_current_time)

    return time_control


@pytest.fixture
def mock_db(monkeypatch):
    """Create a mock database for testing."""
    client = MongoClient()
    # Clear any existing data
    client.drop_database("test_db")

    db = DatabaseClient(client=client, db_name="test_db")

    yield db


# @pytest.fixture
# def test_server_config(monkeypatch):
#     """Set test environment variables."""
#     monkeypatch.setenv("DB_NAME", "test_db")
#     monkeypatch.setenv("DB_HOST", "localhost")
#     monkeypatch.setenv("DB_PORT", "27017")
#     monkeypatch.setenv("ADMIN_USERNAME", "test_admin")
#     monkeypatch.setenv("ADMIN_PASSWORD", "test_password")
#     return ServerConfig()


@pytest.fixture
def queue_args(mock_datetime):
    """Minimum queue args for db create_queue for testing."""
    return {
        "queue_name": "test_queue",
        "password": "test_password",
    }


@pytest.fixture
def task_args(mock_datetime):
    """Minimum task args for db create_task for testing."""
    return {
        "queue_name": "test_queue",
        "task_name": "test_task",
        "args": {"param1": 1},
        "metadata": {"tag": "test"},
    }
