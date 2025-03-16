import concurrent.futures
import os
import random
import threading
import time
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
TOTAL_WORKERS = 20
TOTAL_PRODUCER = 10
TASKS_PER_PRODUCER = 20
TOTAL_TASKS = TOTAL_PRODUCER * TASKS_PER_PRODUCER
AVERAGE_JOB_DELAY = 0.5
AVERAGE_JOB_DELAY_STD = 0.3
AVERAGE_PRODUCER_DELAY = 0.1
AVERAGE_PRODUCER_DELAY_STD = 0.05

# Global
task_fail_cnt = 0
task_fail_cnt_lock = threading.Lock()


def rand_delay(mean, std):
    high_precision_sleep(max(random.gauss(mean, std), 0))


def producer(max_retries=1):
    for i in range(TASKS_PER_PRODUCER):
        rand_delay(AVERAGE_PRODUCER_DELAY, AVERAGE_PRODUCER_DELAY_STD)
        submit_task(
            task_name=f"test_task_{random.randint(0, 1000)}",
            args={
                "arg1": i,
                "arg2": {"arg3": i, "arg4": "foo"},
            },
            max_retries=max_retries,
        )


def create_consumer(should_fail=False):
    """Factory function to create consumers with deterministic behavior."""

    def consumer():
        @loop_run(required_fields=["arg1", "arg2"])
        def run_job():
            rand_delay(AVERAGE_JOB_DELAY, AVERAGE_JOB_DELAY_STD)
            if should_fail:
                with task_fail_cnt_lock:
                    global task_fail_cnt
                    task_fail_cnt += 1
                finish("failed")
            else:
                finish("success")

        run_job()

    return consumer


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


@pytest.fixture(autouse=True)
def setup_task_fail_cnt():
    global task_fail_cnt
    task_fail_cnt = 0
    yield
    task_fail_cnt = 0


@pytest.mark.parametrize(
    "failing_workers,max_retries",
    [
        (0, 1),  # No failing workers, no retries (success case)
        (2, 1),  # 2 failing workers, no retries (failure case)
        (2, 3),  # 2 failing workers, 3 chances
    ],
)
def test_concurrent_producers_and_consumers(failing_workers, max_retries):
    # Create a mix of successful and failing consumers
    consumers = []
    for i in range(TOTAL_WORKERS):
        should_fail = i < failing_workers
        consumers.append(create_consumer(should_fail=should_fail))

    # Start workers and producers concurrently
    with ThreadPoolExecutor(max_workers=TOTAL_WORKERS + TOTAL_PRODUCER) as executor:
        # Submit producers
        producer_futures = [
            executor.submit(lambda: producer(max_retries=max_retries))
            for _ in range(TOTAL_PRODUCER)
        ]

        time.sleep(1.0)  # Give producer time to start up

        # Submit job workers first and give them time to start
        consumer_futures = [executor.submit(consumer) for consumer in consumers]

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

        # Try to get results from consumers (will timeout as they're infinite loops)
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
        len(tasks.content) == TOTAL_TASKS
    ), f"Expected {TOTAL_TASKS} tasks, found {len(tasks.content)}"

    # Verify worker statuses
    workers = ls_workers()
    active_workers = 0
    crashed_workers = 0

    worker_total_retries = 0

    for worker in workers.content:
        worker_total_retries += worker.retries
        if worker.status == "crashed":
            crashed_workers += 1
        elif worker.status == "active":
            active_workers += 1

    assert (
        crashed_workers + active_workers == TOTAL_WORKERS
    ), f"Expected {TOTAL_WORKERS} workers, but got {crashed_workers} failed and {active_workers} active workers."

    assert (
        worker_total_retries == task_fail_cnt
    ), f"Expected {task_fail_cnt} workers to be retried, but got {worker_total_retries}"

    if worker_total_retries == failing_workers * max_retries:
        assert crashed_workers == failing_workers, (
            f"Expected {failing_workers} suspended workers, but got {crashed_workers}. "
            "This assertion error may occur (by chance, which is normal) if the failing worker lagged and didn't reach suspension state before other workers "
            "completed the task."
        )

    # assert crashed_workers == failing_workers, (
    #     f"Expected {failing_workers} suspended workers, but got {crashed_workers}. "
    #     "This assertion error may occur (by chance, which is normal) if the failing worker lagged and didn't reach suspension state before other workers "
    #     "completed the task."
    # )

    assert (
        active_workers == TOTAL_WORKERS - failing_workers
    ), f"Expected to have {TOTAL_WORKERS - failing_workers} active workers, but got {active_workers}"

    # Since we have active workers, we should have no pending tasks
    assert pending_count == 0, (
        f"Expected 0 pending tasks, got Pending: {pending_count}, "
        f"Success: {success_count}, Failed: {failed_count}."
    )

    if failing_workers == 0:
        assert (
            success_count == TOTAL_TASKS
        ), f"Expected {TOTAL_TASKS} successful tasks, got Success: {success_count}, Failed: {failed_count}, Pending: {pending_count}"

    if failed_count > 0:
        for task in tasks.content:
            if task.status == "failed":
                assert (
                    task.retries == max_retries
                ), f"Expected task {task.task_id} to have at least {max_retries} retries, but got {task.retries}"
                assert (
                    task.retries < max_retries + 1
                ), f"Expected task {task.task_id} to have at most {max_retries + 1} retries, but got {task.retries}"

    # Print a summary
    print(
        f"Test run completed with {failing_workers} failing workers and {max_retries} max retries.",
        f"Summary: {TOTAL_TASKS} tasks, {success_count} successful, {failed_count} failed, {pending_count} pending.",
        flush=True,
    )
