import concurrent.futures
import random
import time
from concurrent.futures import ThreadPoolExecutor

from labtasker import (
    create_queue,
    finish,
    get_client_config,
    ls_tasks,
    ls_workers,
    submit_task,
)
from labtasker.client.core.job_runner import (
    _loop_internal_error_handler,
    loop_run,
    set_loop_internal_error_handler,
)

# Constants
TOTAL_WORKERS = 20
TOTAL_PRODUCER = 5
TASKS_PER_PRODUCER = 20
TOTAL_TASKS = TOTAL_PRODUCER * TASKS_PER_PRODUCER
AVERAGE_JOB_DELAY = 0.5
AVERAGE_JOB_DELAY_STD = 0.3
AVERAGE_PRODUCER_DELAY = 0.1
AVERAGE_PRODUCER_DELAY_STD = 0.05


def high_precision_sleep(seconds):
    """High precision sleep implementation."""
    start = time.perf_counter()
    while time.perf_counter() - start < seconds:
        pass


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


def error_handler(e, _):
    print(f"Loop internal error: {e}")
    raise e


def main():
    # Setup queue with your configuration
    client_config = get_client_config()
    create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )

    # Set error handler
    original_handler = _loop_internal_error_handler
    set_loop_internal_error_handler(error_handler)

    try:
        # Start workers and producers concurrently
        with ThreadPoolExecutor(max_workers=TOTAL_WORKERS + TOTAL_PRODUCER) as executor:
            # Submit job workers
            consumer_futures = [executor.submit(consumer) for _ in range(TOTAL_WORKERS)]

            # Submit producers
            producer_futures = [
                executor.submit(producer) for _ in range(TOTAL_PRODUCER)
            ]

            # Wait for producers to complete
            for future in producer_futures:
                try:
                    future.result()
                except Exception as e:
                    print(f"Producer failed with exception: {e}")
                    raise

            # Check tasks
            tasks = ls_tasks(limit=TOTAL_TASKS)
            if not tasks.found:
                raise RuntimeError("No tasks found after test run")

            if len(tasks.content) != TOTAL_TASKS:
                raise RuntimeError(
                    f"Expected {TOTAL_TASKS} tasks, found {len(tasks.content)}"
                )

            # Wait for consumers (with timeout since they're infinite loops)
            for future in consumer_futures:
                try:
                    future.result(timeout=60)
                except concurrent.futures.TimeoutError:
                    pass  # Expected for infinite loops
                except Exception as e:
                    print(f"Worker failed with exception: {e}")
                    raise

        # Final check for task statuses
        tasks = ls_tasks(limit=TOTAL_TASKS)
        if not tasks.found:
            raise RuntimeError("No tasks found after test run")

        if len(tasks.content) != TOTAL_TASKS:
            raise RuntimeError(
                f"Expected {TOTAL_TASKS} tasks, found {len(tasks.content)}"
            )

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
                raise RuntimeError(f"Unexpected task status: {task.status}")

        # Verify that tasks were submitted and processed
        if len(tasks.content) != TOTAL_PRODUCER * TASKS_PER_PRODUCER:
            raise RuntimeError(
                f"Expected {TOTAL_PRODUCER * TASKS_PER_PRODUCER} tasks, found {len(tasks.content)}"
            )

        # Check worker statuses
        workers = ls_workers()
        for worker in workers.content:
            if worker.status == "suspended":
                print(f"Warning: Worker {worker.worker_id} is suspended.")

        # Verify all tasks succeeded
        if success_count != TOTAL_PRODUCER * TASKS_PER_PRODUCER:
            raise RuntimeError(
                f"Expected {TOTAL_PRODUCER * TASKS_PER_PRODUCER} successful tasks, got Pending: {pending_count}, Success: {success_count}, Failed: {failed_count}."
            )

        print(
            f"Concurrency test results: Pending: {pending_count}, Success: {success_count}, Failed: {failed_count}"
        )

    finally:
        # Reset error handler
        set_loop_internal_error_handler(original_handler)


if __name__ == "__main__":
    main()
