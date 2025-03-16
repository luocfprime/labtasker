import concurrent.futures
import os
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import pytest

from labtasker import create_queue, finish, ls_tasks, ls_workers, submit_task
from labtasker.client.core.events import connect_events
from labtasker.client.core.job_runner import loop_run
from tests.fixtures.logging import silence_logger
from tests.test_client.test_core.test_event.utils import dump_events
from tests.utils import high_precision_sleep

if os.environ.get("GITHUB_ACTIONS") == "true":
    pytest.skip(
        f"Skipping {__file__} GH Actions.",
        allow_module_level=True,
    )

pytestmark = [
    # pytest.mark.unit,  # mongomock does not support transaction, cannot guarantee ACID
    # pytest.mark.integration,  # TestClient async in integration result in infinite loop
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
]

# Constants
TOTAL_WORKERS = 10
TOTAL_PRODUCER = 10
TASKS_PER_PRODUCER = 5
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
                if random.uniform(0, 1) < 0.5:  # fail by raise Exception
                    raise Exception("Task failed")
                else:
                    finish("failed")  # fail by finish("failed")
            else:
                finish("success")

        run_job()

    return consumer


@pytest.fixture(autouse=True)
def setup_queue(client_config, db_fixture):
    # relies on db_fixture so that DB is cleaned up after each test
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
def test_concurrent_job_flow_events(failing_workers, max_retries):
    listener = connect_events(timeout=5)

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
    total_task_retries = 0

    for task in tasks.content:
        # if task.retries == max_retries, the last retry is not actually
        # a valid retry, since it directly transition from running -> failed.
        # therefore the actual number of retries (that have been run) is task.retries - 1
        total_task_retries += (
            task.retries if task.retries < max_retries else task.retries - 1
        )
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

    # Test event listener
    # wait a little while
    time.sleep(5.0)
    listener.stop()
    received_events_list = dump_events(listener)
    received_events = defaultdict(int)
    for event_resp in received_events_list:
        received_events[event_resp.event.old_state, event_resp.event.new_state] += 1

    # check if the received events are ordered and consecutive
    received_events_list = sorted(received_events_list, key=lambda r: r.sequence)
    for i in range(len(received_events_list) - 1):
        assert (
            received_events_list[i].sequence + 1 == received_events_list[i + 1].sequence
        ), f"Expected consecutive events, but got {received_events_list[i].sequence} and {received_events_list[i + 1].sequence}"

    # old, new, count
    expected_transitions = [
        # total job creation
        ("created", "pending", TOTAL_TASKS),
        # total worker creation
        ("created", "active", TOTAL_WORKERS),
        # worker crash
        ("active", "crashed", crashed_workers),
        # job execution success
        ("running", "success", success_count),
        # job execution failure
        ("running", "failed", failed_count),
        # job retry
        ("running", "pending", total_task_retries),
    ]

    for old_state, new_state, count in expected_transitions:
        assert (
            received_events[old_state, new_state] == count
        ), f"Expected {count} events from {old_state} to {new_state}, but got {received_events[old_state, new_state]}"
