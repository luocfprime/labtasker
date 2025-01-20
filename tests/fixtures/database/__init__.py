import pytest

from labtasker.constants import Priority

from .mock import mock_db
from .real import real_db


@pytest.fixture
def queue_args():
    """Minimum queue args ~for db create_queue for testing."""
    return {
        "queue_name": "test_queue",
        "password": "test_password",
    }


@pytest.fixture
def get_task_args():
    """Minimum task args for db create_task for testing."""

    def wrapper(queue_id, override_fields=None, args_or_cmd="args"):
        """
        Args:
            override_fields: optionally override given fields
            args_or_cmd: either "args" or "cmd" must be provided for minimalistic task configuration
        """
        assert args_or_cmd in ("args", "cmd")
        result = {
            "queue_id": queue_id,  # this should be set after queue is created
        }
        if args_or_cmd == "args":
            result.update({"args": {"arg1": "value1"}})
        elif args_or_cmd == "cmd":
            result.update({"cmd": "python test.py  --a --b"})

        if override_fields:
            result.update(override_fields)
        return result

    return wrapper


@pytest.fixture
def get_full_task_args():
    """Minimum task args for db create_task for testing."""

    def wrapper(queue_id, override_fields=None):
        result = {
            "queue_id": queue_id,
            "task_name": "test_task",
            "args": {"arg1": "value1", "arg2": "value2"},
            "metadata": {"tags": ["test"]},
            "cmd": "python test.py  --a --b",
            "heartbeat_timeout": 60,  # 60s
            "task_timeout": 300,  # 300s
            "max_retries": 3,
            "priority": Priority.MEDIUM,
        }

        if override_fields:
            result.update(override_fields)

        return result

    return wrapper


@pytest.fixture
def db_fixture(test_type, request):
    """
    Dynamic database fixture that supports both mock and real databases.
    """
    if test_type == "integration":  # prioritize integration tests over unit tests
        return request.getfixturevalue("real_db")
    elif test_type == "unit":
        return request.getfixturevalue("mock_db")
    else:
        raise ValueError(
            "Database testcases must be tagged with either 'unit' or 'integration'"
        )
