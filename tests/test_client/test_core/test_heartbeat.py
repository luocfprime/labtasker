import os
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.status import HTTP_204_NO_CONTENT

from labtasker.client.core.exceptions import LabtaskerRuntimeError
from labtasker.client.core.heartbeat import end_heartbeat, start_heartbeat
from labtasker.client.core.logging import logger
from labtasker.client.core.paths import set_labtasker_log_dir
from labtasker.security import get_auth_headers

pytestmark = [pytest.mark.unit]


class Counter:
    def __init__(self):
        self.count = 0
        self._lock = threading.Lock()

    def incr(self):
        with self._lock:
            self.count += 1

    def get(self):
        with self._lock:
            return self.count

    def reset(self):
        with self._lock:
            self.count = 0


cnt = Counter()
app = FastAPI()


@app.post(
    "/api/v1/queues/me/tasks/{task_id}/heartbeat", status_code=HTTP_204_NO_CONTENT
)
def mock_refresh_task_heartbeat_endpoint(
    task_id: str,
):
    cnt.incr()
    logger.debug(f"Received heartbeat for task {task_id}, cnt after incr: {cnt.get()}")


@pytest.fixture
def test_app_():
    return TestClient(app)


@pytest.fixture(autouse=True)
def patch_up(monkeypatch, client_config, test_app_):
    """The refresh_heartbeat endpoint should be patched"""
    auth_headers = get_auth_headers(
        client_config.queue.queue_name, client_config.queue.password
    )
    test_app_.headers.update(
        {**auth_headers, "Content-Type": "application/json"},
    )
    monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app_)


@pytest.fixture(autouse=True)
def setup_log_dir():
    set_labtasker_log_dir("test_task_id", set_env=True, overwrite=True)


def test_heartbeat():
    if os.environ.get("GITHUB_ACTIONS", False):
        pytest.skip(
            "Skipping test_heartbeat on Github Actions because of slow CI (which leads to false alarms)."
        )

    logger.debug("test_heartbeat entered...")
    start_heartbeat("test_task_id", heartbeat_interval=0.1)

    # try to start again
    with pytest.raises(LabtaskerRuntimeError):
        start_heartbeat("test_task_id", heartbeat_interval=0.1, raise_error=True)

    time.sleep(0.5)
    assert 4 <= cnt.get() <= 6, cnt.get()
    end_heartbeat()
    time.sleep(0.5)
    assert cnt.get() <= 6, cnt.get()  # should stops after end_heartbeat()

    # try to stop again
    with pytest.raises(LabtaskerRuntimeError):
        end_heartbeat(raise_error=True)
