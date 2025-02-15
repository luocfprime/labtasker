import pytest

from labtasker import create_queue, finish, loop, submit_task, task_info

pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.e2e,
]


@pytest.fixture(autouse=True)
def setup_queue():
    return create_queue(
        queue_name="test-queue",
        password="test-password",
        metadata={"tag": "test"},
    )


@pytest.fixture
def setup_tasks(db_fixture):
    # relies on db_fixture to clear db after each test case
    for i in range(10):
        submit_task(
            task_name=f"test_task_{i}",
            args={
                "arg1": i,
                "arg2": {"arg3": i, "arg4": "foo"},
            },
        )


def test_job_success():
    cnt = 0

    @loop(required_fields=["arg1", "arg2"], eta_max="1h", pass_args_dict=True)
    def job(args):
        nonlocal cnt
        task_name = task_info().task_name
        assert task_name == f"test_task_{cnt}"
        assert args["arg1"] == cnt
        assert args["arg2"]["arg3"] == cnt
        finish("success")
        cnt += 1


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
