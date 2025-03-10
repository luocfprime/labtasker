import concurrent.futures
import random
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from labtasker import create_queue, finish, ls_tasks, ls_worker, submit_task
from labtasker.client.core.job_runner import loop_run, set_loop_internal_error_handler
from tests.fixtures.logging import silence_logger
from tests.utils import high_precision_sleep

pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
]

# Constants
TOTAL_WORKERS = 20
TOTAL_PRODUCER = 5
TASKS_PER_PRODUCER = 20
TOTAL_TASKS = TOTAL_PRODUCER * TASKS_PER_PRODUCER
FAILURE_RATE_PER_WORKER = 0.02
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
        )


def consumer():
    @loop_run(required_fields=["arg1", "arg2"])
    def run_job():
        rand_delay(AVERAGE_JOB_DELAY, AVERAGE_JOB_DELAY_STD)
        success = random.uniform(0, 1) > FAILURE_RATE_PER_WORKER
        if success:
            finish("success")
        else:
            finish("failed")

    run_job()


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


@pytest.fixture(autouse=True)
def setup_loop_internal_error_handler():
    def handler(e):
        pytest.fail(f"Loop internal error: {e}")

    set_loop_internal_error_handler(handler)
    yield
    set_loop_internal_error_handler(lambda e: None)


def test_concurrent_producers_and_consumers():
    # Track completion
    completed_tasks = 0
    failed_tasks = 0

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

        # Give workers some time to process tasks
        time.sleep(5)

        for future in consumer_futures:
            try:
                future.result(timeout=60)
            except concurrent.futures.TimeoutError:
                pytest.fail("Worker timed out")
                pass  # Expected for infinite loops
            except Exception as e:
                pytest.fail(f"Worker failed with exception: {e}")

    # Final check for task statuses
    tasks = ls_tasks()
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

    # Verify that tasks were submitted
    assert (
        len(tasks.content) == TOTAL_PRODUCER * TASKS_PER_PRODUCER
    ), f"Expected {TOTAL_PRODUCER * TASKS_PER_PRODUCER} tasks, found {len(tasks.content)}"

    # Verify that all tasks should be processed if worker are not all suspended
    workers = ls_worker()
    all_suspended = True
    for worker in workers.content:
        if worker.status != "suspended":
            all_suspended = False
            break

    if not all_suspended:
        assert pending_count == 0, (
            f"Expected 0 pending tasks, got Pending: {pending_count}, Success: {success_count}, Failed: {failed_count}."
            f"By a tiny chance, this is happening due to a probability of FAILURE_RATE_PER_WORKER. Try run this test again "
            f"and see if the error persists."
        )

    # Check no internal loop errors occurred (which would have triggered the error handler and failed the test)
