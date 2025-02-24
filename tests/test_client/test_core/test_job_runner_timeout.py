"""
These tests test timeout behavior in end-to-end tests.
Note: they are quite time-consuming.
"""

import os
import time

import pytest

from labtasker import create_queue, loop, ls_tasks, submit_task
from labtasker.client.core.context import set_current_worker_id
from labtasker.client.core.paths import get_labtasker_log_dir
from tests.fixtures.logging import silence_logger

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
]
TOTAL_TASKS = 5


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


@pytest.fixture(autouse=True)
def reset_worker_id():
    set_current_worker_id(None)


@pytest.fixture
def setup_tasks(db_fixture):
    # relies on db_fixture to clear db after each test case
    for i in range(TOTAL_TASKS):
        submit_task(
            task_name=f"test_task_{i}",
            args={
                "arg1": i,
                "arg2": {"arg3": i, "arg4": "foo"},
            },
        )


def delay(interval: float):
    cycles = int(interval // 0.01)
    for _ in range(cycles):
        time.sleep(0.01)


def trigger_heartbeat_thread_termination():
    # This is a bit of a hack.
    # The heartbeat thread will stop once the lock file is deleted.
    # Only use this for testing. Do not use this practice.
    heartbeat_lock = get_labtasker_log_dir() / f"heartbeat.lock"
    if heartbeat_lock.exists():
        os.unlink(heartbeat_lock)


def test_job_task_timeout(setup_tasks, server_config):
    cnt = 0

    max_retries = 1  # only 1 attempt, since it is quite time-consuming

    timeout = server_config.periodic_task_interval / 2

    @loop(
        required_fields=["arg1", "arg2"],
        eta_max=f"{timeout}sec",  # set task timeout
        create_worker_kwargs={"max_retries": max_retries},
        pass_args_dict=True,
    )
    def job(args):
        nonlocal cnt
        cnt += 1
        delay(timeout * 3)

    job()

    assert cnt == max_retries, str(cnt)

    tasks = ls_tasks()
    assert tasks.found
    for task in tasks.content:
        # all failed tasks should be rejoined into the queue
        # since the most recently failed task will join at the end
        assert task.status == "pending"

    # at least one of the tasks should have retries > 0
    assert not all(task.retries == 0 for task in tasks.content), str(tasks.content)


def test_job_heartbeat_timeout(setup_tasks, server_config):
    cnt = 0

    max_retries = 1  # only 1 attempt, since it is quite time-consuming

    timeout = server_config.periodic_task_interval / 2

    @loop(
        required_fields=["arg1", "arg2"],
        heartbeat_timeout=timeout,
        create_worker_kwargs={"max_retries": max_retries},
        pass_args_dict=True,
    )
    def job(args):
        nonlocal cnt
        cnt += 1
        trigger_heartbeat_thread_termination()  # stop heartbeat (hack)
        delay(timeout * 3)

    job()

    assert cnt == max_retries, str(cnt)

    tasks = ls_tasks()
    assert tasks.found
    for task in tasks.content:
        # all failed tasks should be rejoined into the queue
        # since the most recently failed task will join at the end
        assert task.status == "pending"

    assert not all(task.retries == 0 for task in tasks.content), str(tasks.content)
