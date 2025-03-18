import pytest

from labtasker.client.core.exceptions import LabtaskerRuntimeError
from labtasker.client.core.job_runner import (
    _loop_internal_error_handler,
    set_loop_internal_error_handler,
)


@pytest.fixture(autouse=True)
def setup_loop_internal_error_handler():
    """For timeout tests, we need to disable the InvalidStateTransition: Cannot transition from pending to success."""

    def handler(e, _):
        # ignore errors so that timeout tasks does not
        # give you a "500: InvalidStateTransition: Cannot transition from pending to success."
        if "InvalidStateTransition" in str(e) and "from pending to" in str(e):
            return

        # When timeout job loop eventually reports task status
        # after exceeding a timeout period, the job could be assigned to a different worker (or the worker_id set to None)
        # Either way, it would trigger a LabtaskerRuntimeError, which is the expected behaviour.
        # We need to ignore this error.
        if isinstance(
            e, LabtaskerRuntimeError
        ) and "Current task is assigned to a different worker" in str(e):
            return

        raise e

    original_handler = _loop_internal_error_handler
    set_loop_internal_error_handler(handler)
    yield
    set_loop_internal_error_handler(original_handler)
