import time

import pytest

from labtasker.client.core.api import (
    create_queue,
    create_worker,
    fetch_task,
    submit_task,
)
from labtasker.client.core.heartbeat import start_heartbeat
from labtasker.client.core.paths import set_labtasker_log_dir
from tests.fixtures.logging import silence_logger

pytestmark = [
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


@pytest.fixture(autouse=True)
def setup_workers():
    id1 = create_worker(worker_name="worker_1")
    id2 = create_worker(worker_name="worker_2")

    return id1, id2


@pytest.fixture(autouse=True)
def setup_task(db_fixture):
    # relies on db_fixture to clear db after each test case

    fetch_task()


def test_heartbeat_worker_mismatch():
    # Test if heartbeat fails when worker_id does not match

    # setup
    # 1. create tasks
    submit_task(task_name="test_task", args={"arg1": 0})
    # 2. create workers
    worker_id1 = create_worker(worker_name="worker_1")
    worker_id2 = create_worker(worker_name="worker_2")
    # 3. fetch task
    task_resp = fetch_task(worker_id=worker_id1, heartbeat_timeout=99999.0)

    # 4. set local dir
    task_id = task_resp.task.task_id
    set_labtasker_log_dir(
        task_id=task_id,
        task_name=task_resp.task.task_name,
        set_env=True,
        overwrite=True,
    )

    # use a different worker_id to start heartbeat
    heartbeat_manager = start_heartbeat(
        task_id=task_id, worker_id=worker_id2, heartbeat_interval=0.2
    )
    time.sleep(1.0)
    assert not heartbeat_manager.is_alive()
