import pytest
from pydantic import SecretStr

from labtasker.api_models import QueueCreateRequest, TaskSubmitRequest
from labtasker.security import get_auth_headers


@pytest.fixture
def queue_create_request():
    return QueueCreateRequest(
        queue_name="test_queue",
        password=SecretStr("test_password"),
        metadata={"tag": "test"},
    )


@pytest.fixture
def task_submit_request():
    """Test task data."""
    return TaskSubmitRequest(
        task_name="test_task",
        args={"param1": 1},
        metadata={"test": "data"},
    )


@pytest.fixture
def auth_headers(queue_create_request):
    return get_auth_headers(
        queue_create_request.queue_name, queue_create_request.password
    )
