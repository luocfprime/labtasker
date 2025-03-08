import time

import pytest
from typing_extensions import Annotated

from labtasker import create_queue, finish, ls_tasks, submit_task, task_info
from labtasker.client.client_api import Required, loop
from labtasker.client.core.context import set_current_worker_id
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
                "arg2": {
                    "arg3": i,
                    "arg4": "foo",
                    "arg5": {"arg6": "bar"},
                },
            },
        )


@pytest.fixture(autouse=True)
def reset_worker_id():
    set_current_worker_id(None)


class TestRegularBehaviour:
    """Test regular behaviour like run_loop"""

    def test_job_success(self, setup_tasks):
        tasks = ls_tasks()
        assert tasks.found
        assert len(tasks.content) == TOTAL_TASKS

        idx = -1

        @loop(required_fields=["arg1", "arg2"], eta_max="1h", pass_args_dict=True)
        def job(args):
            nonlocal idx
            idx += 1
            task_name = task_info().task_name
            assert task_name == f"test_task_{idx}"
            assert args["arg1"] == idx
            assert args["arg2"]["arg3"] == idx

            time.sleep(
                0.5
            )  # a tiny delay to ensure the tasks api request are processed

            finish("success")

        job()

        assert idx + 1 == TOTAL_TASKS, idx

        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            assert task.status == "success"

    def test_job_manual_failure(self, setup_tasks):
        cnt = 0

        max_retries = 3

        @loop(
            required_fields=["arg1", "arg2"],
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
            pass_args_dict=True,
        )
        def job(args):
            nonlocal cnt
            cnt += 1
            time.sleep(
                0.5
            )  # a tiny delay to ensure the tasks api request are processed
            finish("failed")

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

        assert total_retries == max_retries, total_retries

    def test_job_auto_failure(self, setup_tasks):
        cnt = 0

        max_retries = 3

        @loop(
            required_fields=["arg1", "arg2"],
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
            pass_args_dict=True,
        )
        def job(args):
            nonlocal cnt
            cnt += 1
            time.sleep(
                0.5
            )  # a tiny delay to ensure the tasks api request are processed

            assert False  # the exception should be caught in loop and auto reported

        job()

        assert cnt == max_retries, cnt

        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            # all failed tasks should be rejoined into the queue
            # since the most recently failed task will join at the end
            assert task.status == "pending"


class TestRunnerWithResolver:
    """Test the loop with resolver"""

    def test_job_success(self, setup_tasks):
        tasks = ls_tasks()
        assert tasks.found
        assert len(tasks.content) == TOTAL_TASKS

        idx = -1

        def arg2_arg3_to_str(arg2):
            """A custom defined resolver"""
            arg2["arg3"] = str(arg2["arg3"])
            return arg2

        @loop(eta_max="1h")
        def job(
            arg1: Annotated[int, Required()],  # annotation
            arg2: Annotated[dict, Required(resolver=arg2_arg3_to_str)],  # resolver
            arg_bar: str = Required(alias="arg2.arg5.arg6"),  # alias and as default
            task_args=None,
        ):
            nonlocal idx
            idx += 1
            task_name = task_info().task_name
            assert task_name == f"test_task_{idx}"
            assert arg1 == idx
            assert arg2["arg3"] == f"{idx}"
            assert arg_bar == "bar"

            time.sleep(
                0.5
            )  # a tiny delay to ensure the tasks api request are processed

            finish("success")

        job()

        assert idx + 1 == TOTAL_TASKS, idx

        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            assert task.status == "success"

    def test_job_manual_failure(self, setup_tasks):
        cnt = 0

        max_retries = 3

        @loop(
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
        )
        def job(
            arg1: Annotated[int, Required()],
            arg2: Annotated[dict, Required()],
            task_args=None,
        ):
            nonlocal cnt
            cnt += 1
            time.sleep(
                0.5
            )  # a tiny delay to ensure the tasks api request are processed
            finish("failed")

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

        assert total_retries == max_retries, total_retries

    def test_job_auto_failure(self, setup_tasks):
        cnt = 0

        max_retries = 3

        @loop(
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
        )
        def job(
            arg1: Annotated[int, Required()],
            arg2: Annotated[dict, Required()],
            task_args=None,
        ):
            nonlocal cnt
            cnt += 1
            time.sleep(
                0.5
            )  # a tiny delay to ensure the tasks api request are processed

            assert False  # the exception should be caught in loop and auto reported

        job()

        assert cnt == max_retries, cnt

        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            # all failed tasks should be rejoined into the queue
            # since the most recently failed task will join at the end
            assert task.status == "pending"
