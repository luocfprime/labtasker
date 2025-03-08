import pytest

from labtasker.constants import Priority


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
            queue_id:
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
