import os
import shutil
import sys
from io import StringIO
from pathlib import Path
from shutil import rmtree

import pytest

from labtasker.client.core.config import (
    ClientConfig,
    get_client_config,
    init_labtasker_root,
    load_client_config,
)
from labtasker.client.core.context import set_current_worker_id
from labtasker.client.core.heartbeat import end_heartbeat
from labtasker.client.core.job_runner import (
    _loop_internal_error_handler,
    set_loop_internal_error_handler,
    set_prompt_on_task_failure,
)
from labtasker.security import get_auth_headers
from tests.fixtures.server.sync_app import test_app


@pytest.fixture(autouse=True)
def patch_httpx_client(monkeypatch, test_type, test_app, client_config):
    """Patch the httpx client"""
    if test_type in ["unit", "integration"]:
        auth_headers = get_auth_headers(
            client_config.queue.queue_name, client_config.queue.password
        )
        test_app.headers.update(
            {**auth_headers, "Content-Type": "application/json"},
        )
        monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app)

    # For e2e test, we serve the API service via docker and test with actual httpx client.


@pytest.fixture(autouse=True)
def labtasker_test_root(proj_root, monkeypatch):
    """Setup labtasker test root dir and default client config"""
    labtasker_test_root = Path(os.path.join(proj_root, "tmp", ".labtasker"))
    if labtasker_test_root.exists():
        rmtree(labtasker_test_root)

    init_labtasker_root(labtasker_root=labtasker_test_root, exist_ok=True)

    os.environ["LABTASKER_ROOT"] = str(labtasker_test_root)

    # Patch the constants
    monkeypatch.setattr(
        "labtasker.client.core.paths._LABTASKER_ROOT", labtasker_test_root
    )

    yield labtasker_test_root

    # Tear Down
    rmtree(labtasker_test_root)


@pytest.fixture(autouse=True)
def client_config(labtasker_test_root) -> ClientConfig:
    load_client_config(skip_if_loaded=False, disable_warning=True)  # reload client env
    return get_client_config()


@pytest.fixture(autouse=True)
def reset_heartbeat():
    """Reset heartbeat manager after each testcase. So that some crashed test does not affect others."""
    yield
    end_heartbeat(raise_error=False)


@pytest.fixture(autouse=True)
def reset_worker_id():
    yield
    set_current_worker_id(None)


@pytest.fixture(autouse=True)
def setup_loop_internal_error_handler():
    def handler(e, _):
        pytest.fail(f"Loop internal error: {e}")

    original_handler = _loop_internal_error_handler
    set_loop_internal_error_handler(handler)
    yield
    set_loop_internal_error_handler(original_handler)


@pytest.fixture(autouse=True)
def disable_prompt_on_task_failure():
    set_prompt_on_task_failure(enabled=False)


@pytest.fixture(autouse=True)
def patch_job_runner_print_exception(monkeypatch):
    def no_op(*args, **kwargs):
        pass

    monkeypatch.setattr(
        "labtasker.client.core.job_runner.stderr_console.print_exception", no_op
    )


@pytest.fixture
def capture_output(monkeypatch):
    """
    Fixture that captures stdout and stderr without displaying
    anything in the console during tests.

    Usage:
    def test_example(capture_output):
        print("normal output")  # Won't show in console
        print("error output", file=sys.stderr)  # Won't show in console

        assert "normal output" in capture_output.stdout
        assert "error output" in capture_output.stderr
    """
    # Capture buffers
    stdout_buffer = StringIO()
    stderr_buffer = StringIO()

    # Redirect standard output and error
    monkeypatch.setattr(sys, "stdout", stdout_buffer)
    monkeypatch.setattr(sys, "stderr", stderr_buffer)

    # Create a handle class with access to captured outputs
    class OutputCapture:
        @property
        def stdout(self):
            """Get captured standard output"""
            return stdout_buffer.getvalue()

        @property
        def stderr(self):
            """Get captured standard error"""
            return stderr_buffer.getvalue()

        def clear_all(self):
            """Clear all capture buffers"""
            self.clear_stdout()
            self.clear_stderr()

        def clear_stdout(self):
            """Clear only stdout buffer"""
            stdout_buffer.truncate(0)
            stdout_buffer.seek(0)

        def clear_stderr(self):
            """Clear only stderr buffer"""
            stderr_buffer.truncate(0)
            stderr_buffer.seek(0)

    return OutputCapture()


@pytest.fixture(autouse=True)
def skip_if_terminal_too_narrow():
    """
    Some tests require reading from output. And a narrow terminal may cause unexpected test failures (false positive).
    """
    terminal_width, _ = shutil.get_terminal_size(
        (80, 24)
    )  # Default to 80 if unavailable
    if terminal_width < 80:
        pytest.skip(f"Skipping test: Terminal width ({terminal_width}) is less than 80")
