import concurrent.futures
import os
import random
from concurrent.futures import ThreadPoolExecutor

import pytest

from labtasker import create_queue, finish, ls_tasks, ls_workers, submit_task
from labtasker.client.core.job_runner import loop_run
from tests.fixtures.logging import server_logger_level_to_error, silence_logger
from tests.utils import high_precision_sleep

if os.environ.get("GITHUB_ACTIONS") == "true":
    pytest.skip(
        "Skipping test_runner_high_concurrency.py in GH Actions.",
        allow_module_level=True,
    )

pytestmark = [
    # pytest.mark.unit,  # mongomock does not support transaction, cannot guarantee ACID
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
    pytest.mark.usefixtures(
        "server_logger_level_to_error"
    ),  # hide transaction retry warnings. If you want to see retry warnings, remove this line
]

# Constants
TOTAL_WORKERS = 25
TOTAL_PRODUCER = 10
TASKS_PER_PRODUCER = 20
TOTAL_TASKS = TOTAL_PRODUCER * TASKS_PER_PRODUCER
AVERAGE_JOB_DELAY = 0.5
AVERAGE_JOB_DELAY_STD = 0.3
AVERAGE_PRODUCER_DELAY = 0.1
AVERAGE_PRODUCER_DELAY_STD = 0.05


def rand_delay(mean, std):
    high_precision_sleep(max(random.gauss(mean, std), 0))


def producer():
    for i in range(TASKS_PER_PRODUCER):
        rand_delay(AVERAGE_PRODUCER_DELAY, AVERAGE_PRODUCER_DELAY_STD)
        submit_task(
            task_name=f"test_task_{random.randint(0, 1000)}",
            args={
                "arg1": i,
                "arg2": {"arg3": i, "arg4": "foo"},
            },
            max_retries=1,
        )


def consumer():
    @loop_run(required_fields=["arg1", "arg2"])
    def run_job():
        rand_delay(AVERAGE_JOB_DELAY, AVERAGE_JOB_DELAY_STD)
        finish("success")

    run_job()


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


def test_concurrent_producers_and_consumers():
    # Start workers and producers concurrently
    with ThreadPoolExecutor(max_workers=TOTAL_WORKERS + TOTAL_PRODUCER) as executor:
        # Submit job workers
        consumer_futures = [executor.submit(consumer) for _ in range(TOTAL_WORKERS)]

        # Submit producers
        producer_futures = [executor.submit(producer) for _ in range(TOTAL_PRODUCER)]

        # Wait for producers to complete
        for future in producer_futures:
            try:
                future.result()
            except Exception as e:
                pytest.fail(f"Producer failed with exception: {e}")

        tasks = ls_tasks(limit=TOTAL_TASKS)
        assert tasks.found, "No tasks found after test run"
        assert (
            len(tasks.content) == TOTAL_TASKS
        ), f"Expected {TOTAL_TASKS} tasks, found {len(tasks.content)}"

        for future in consumer_futures:
            try:
                future.result(timeout=60)
            except concurrent.futures.TimeoutError:
                pytest.fail("Worker timed out")
                pass  # Expected for infinite loops
            except Exception as e:
                pytest.fail(f"Worker failed with exception: {e}")

    # Final check for task statuses
    tasks = ls_tasks(limit=TOTAL_TASKS)
    assert tasks.found, "No tasks found after test run"
    assert (
        len(tasks.content) == TOTAL_TASKS
    ), f"Expected {TOTAL_TASKS} tasks, found {len(tasks.content)}"

    success_count = 0
    failed_count = 0
    pending_count = 0

    for task in tasks.content:
        if task.status == "success":
            success_count += 1
        elif task.status == "failed":
            failed_count += 1
        elif task.status == "pending":
            pending_count += 1
        else:
            pytest.fail(f"Unexpected task status: {task.status}")

    # Verify that tasks were submitted
    assert (
        len(tasks.content) == TOTAL_PRODUCER * TASKS_PER_PRODUCER
    ), f"Expected {TOTAL_PRODUCER * TASKS_PER_PRODUCER} tasks, found {len(tasks.content)}"

    workers = ls_workers()
    for worker in workers.content:
        assert worker.status != "suspended", f"Worker {worker.worker_id} is suspended."

    assert (
        success_count == TOTAL_PRODUCER * TASKS_PER_PRODUCER
    ), f"Expected {TOTAL_PRODUCER * TASKS_PER_PRODUCER} successful tasks, got Pending: {pending_count}, Success: {success_count}, Failed: {failed_count}."
    print(
        f"Test runner concurrency with failure rate = 0, result: Pending: {pending_count}, Success: {success_count}, Failed: {failed_count}."
    )
    # Check no internal loop errors occurred (which would have triggered the error handler and failed the test)
