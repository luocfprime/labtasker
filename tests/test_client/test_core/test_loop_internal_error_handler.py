import pytest

from labtasker import create_queue, submit_task
from labtasker.client.core.job_runner import (
    _loop_internal_error_handler,
    loop_run,
    set_loop_internal_error_handler,
)
from tests.fixtures.logging import silence_logger

pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
]


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


class CustomError(Exception):
    pass


@pytest.fixture(autouse=True)
def setup_loop_internal_error_handler():
    def handler(e, _):
        raise CustomError("custom")

    original_handler = _loop_internal_error_handler
    set_loop_internal_error_handler(handler)
    yield
    set_loop_internal_error_handler(original_handler)


def test_loop_internal_error_handler(monkeypatch):
    """Test if the set_loop_internal_error_handler actually raises CustomError"""

    # monkey patch the fetch_task in loop_run to raise an error
    def mock_fetch_task(*args, **kwargs):
        raise ValueError("test")

    monkeypatch.setattr("labtasker.client.core.job_runner.fetch_task", mock_fetch_task)

    # create a task
    submit_task(
        task_name="test_task",
        args={
            "arg1": 0,
            "arg2": 1,
        },
    )

    @loop_run(required_fields=["arg1", "arg2"])
    def run_job():
        pass

    with pytest.raises(CustomError, match="custom"):
        run_job()
