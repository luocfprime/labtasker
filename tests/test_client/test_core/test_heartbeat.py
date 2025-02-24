import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.status import HTTP_204_NO_CONTENT

from labtasker.client.core.exceptions import LabtaskerRuntimeError
from labtasker.client.core.heartbeat import end_heartbeat, start_heartbeat
from labtasker.client.core.paths import set_labtasker_log_dir

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


@pytest.fixture
def test_app():
    return TestClient(app)


@pytest.fixture(autouse=True)
def setup_log_dir():
    set_labtasker_log_dir("test_task_id", set_env=True, overwrite=True)


def test_heartbeat(test_app):
    start_heartbeat("test_task_id", heartbeat_interval=0.1)

    # try to start again
    with pytest.raises(LabtaskerRuntimeError):
        start_heartbeat("test_task_id", heartbeat_interval=0.1, raise_error=True)

    time.sleep(0.5)
    assert 4 <= cnt.get() <= 6, cnt.get()
    end_heartbeat()
    time.sleep(0.5)
    assert cnt.get() <= 6, cnt.get()

    # try to stop again
    with pytest.raises(LabtaskerRuntimeError):
        end_heartbeat(raise_error=True)
