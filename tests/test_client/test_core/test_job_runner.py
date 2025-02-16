import time

import pytest

from labtasker import create_queue, finish, loop, ls_tasks, submit_task, task_info

pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.e2e,
]

TOTAL_TASKS = 5


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue_name,
        password=client_config.password.get_secret_value(),
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


def test_job_success(setup_tasks):
    tasks = ls_tasks()
    assert tasks.found
    assert len(tasks.content) == TOTAL_TASKS

    cnt = -1

    @loop(required_fields=["arg1", "arg2"], eta_max="1h", pass_args_dict=True)
    def job(args):
        nonlocal cnt
        cnt += 1
        task_name = task_info().task_name
        assert task_name == f"test_task_{cnt}"
        assert args["arg1"] == cnt
        assert args["arg2"]["arg3"] == cnt
        finish("success")
        time.sleep(0.1)
        print(cnt)

    job()

    assert cnt + 1 == TOTAL_TASKS, cnt

    tasks = ls_tasks()
    assert tasks.found
    for task in tasks.content:
        assert task.status == "success"


# def test_job_failure():
#
#     @loop()
#     def job():
#         ...
#         finish("failure")
#
#     ...
#
#
# def test_job_heartbeat_timeout(): ...
