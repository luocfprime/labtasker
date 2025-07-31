import time

import pytest

from labtasker import (
    LabtaskerHTTPStatusError,
    create_queue,
    finish,
    get_queue,
    ls_tasks,
    submit_task,
    task_info,
)
from labtasker.client.core.job_runner import loop_run
from tests.fixtures.logging import silence_logger

pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
]

TOTAL_TASKS = 3


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


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


def test_no_auth(db_fixture, capture_output):
    db_fixture.erase()  # wipe the db so that the queue is not created
    with pytest.raises(LabtaskerHTTPStatusError):
        get_queue()  # should trigger a http 401 error

    with pytest.raises(LabtaskerHTTPStatusError):
        loop_run(required_fields=["*"])(lambda: None)
        assert (
            "Either invalid credentials or queue not created." in capture_output.stderr
        )


def test_job_success(setup_tasks):
    tasks = ls_tasks()
    assert tasks.found
    assert len(tasks.content) == TOTAL_TASKS

    idx = -1

    @loop_run(required_fields=["arg1", "arg2"], eta_max="1h", pass_args_dict=True)
    def job(args):
        nonlocal idx
        idx += 1
        task_name = task_info().task_name
        assert task_name == f"test_task_{idx}"
        assert args["arg1"] == idx
        assert args["arg2"]["arg3"] == idx

        time.sleep(0.5)  # a tiny delay to ensure the tasks api request are processed

        finish("success")

    job()

    assert idx + 1 == TOTAL_TASKS, idx

    tasks = ls_tasks()
    assert tasks.found
    for task in tasks.content:
        assert task.status == "success"


def test_job_str_filter(setup_tasks):
    """Test if Pythonic query str as extra_filter works"""
    tasks = ls_tasks()
    assert tasks.found
    assert len(tasks.content) == TOTAL_TASKS

    idx = -1

    @loop_run(
        required_fields=["arg1", "arg2"],
        eta_max="1h",
        pass_args_dict=True,
        extra_filter="args.arg2.arg3 < 2",  # only run the first two tasks
    )
    def job(args):
        nonlocal idx
        idx += 1
        task_name = task_info().task_name
        assert task_name == f"test_task_{idx}"
        assert args["arg1"] == idx
        assert args["arg2"]["arg3"] == idx

        time.sleep(0.5)  # a tiny delay to ensure the tasks api request are processed

        finish("success")

    job()

    assert idx + 1 == 2, idx

    tasks = ls_tasks(extra_filter="args.arg2.arg3 < 2")
    assert tasks.found
    for task in tasks.content:
        assert task.status == "success"


def test_job_manual_failure(setup_tasks):
    cnt = 0

    max_retries = 3

    @loop_run(
        required_fields=["arg1", "arg2"],
        eta_max="1h",
        create_worker_kwargs={"max_retries": max_retries},
        pass_args_dict=True,
    )
    def job(args):
        nonlocal cnt
        cnt += 1
        time.sleep(0.5)  # a tiny delay to ensure the tasks api request are processed
        finish("failed", summary={"reason": "manual failure"})

    job()

    assert cnt == max_retries, cnt

    tasks = ls_tasks()
    assert tasks.found

    total_retries = 0
    for task in tasks.content:
        # all failed tasks should be rejoined into the queue
        # since the most recently failed task will join at the end
        assert task.status == "pending"
        total_retries += task.retries

        if task.retries > 0:
            assert task.summary == {"reason": "manual failure"}

    assert total_retries == max_retries, total_retries


def test_job_auto_failure(setup_tasks):
    cnt = 0

    max_retries = 3

    @loop_run(
        required_fields=["arg1", "arg2"],
        eta_max="1h",
        create_worker_kwargs={"max_retries": max_retries},
        pass_args_dict=True,
    )
    def job(args):
        nonlocal cnt
        cnt += 1
        time.sleep(0.5)  # a tiny delay to ensure the tasks api request are processed

        assert False  # the exception should be caught in loop and auto reported

    job()

    assert cnt == max_retries, cnt

    tasks = ls_tasks()
    assert tasks.found
    for task in tasks.content:
        # all failed tasks should be rejoined into the queue
        # since the most recently failed task will join at the end
        assert task.status == "pending"
