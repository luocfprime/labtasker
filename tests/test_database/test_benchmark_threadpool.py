import asyncio
import uuid

import pytest

from labtasker.concurrent import run_in_threadpool


# Benchmark hyperparameters
class BenchmarkConfig:
    NUM_QUEUES = 20
    TASKS_PER_QUEUE = 100
    TASKS_TO_PROCESS = 40  # Number of tasks to fetch and process per queue


def generate_unique_queue_args(queue_args, suffix):
    """Helper to create unique queue args by adding a suffix to queue_name."""
    new_args = queue_args.copy()
    new_args["queue_name"] = (
        f"{queue_args['queue_name']}_{suffix}_{uuid.uuid4().hex[:8]}"
    )
    return new_args


@pytest.mark.skip(
    reason="this benchmark is no longer necessary because fastapi has its own threadpool."
)
@pytest.mark.benchmark
class TestBenchmarkThreadpool:
    """Benchmark tests comparing synchronous vs threadpool DB operations."""

    @pytest.mark.integration
    def test_queue_grouped(self, benchmark, db_fixture, queue_args, get_task_args):
        """Benchmark queue-grouped processing where operations are grouped by queue.

        API calls per benchmark run:
        - create_queue: {NUM_QUEUES} calls
        - create_task: {NUM_QUEUES * TASKS_PER_QUEUE} calls
        - fetch_task: {NUM_QUEUES * TASKS_TO_PROCESS} calls
        - update_task_status: {NUM_QUEUES * TASKS_TO_PROCESS} calls (mix of success/failure)
        """

        def queue_grouped_processing():
            assert db_fixture.is_empty()

            run_id = uuid.uuid4().hex[:8]  # Unique ID for this benchmark run
            results = []
            # Create multiple queues with tasks
            for i in range(BenchmarkConfig.NUM_QUEUES):
                # Create queue with unique name
                queue_args_i = generate_unique_queue_args(
                    queue_args, f"sync_{run_id}_{i}"
                )
                queue_id = db_fixture.create_queue(**queue_args_i)

                # Create tasks per queue
                task_ids = []
                for j in range(BenchmarkConfig.TASKS_PER_QUEUE):
                    task_args = get_task_args(queue_id)
                    task_args["task_name"] = f"task_{i}_{j}"  # Unique task names
                    task_id = db_fixture.create_task(**task_args)
                    task_ids.append(task_id)

                # Fetch and update tasks
                for _ in range(BenchmarkConfig.TASKS_TO_PROCESS):
                    task = db_fixture.fetch_task(queue_id=queue_id)
                    if task:
                        # Update task status with random success/failure
                        status = "success" if _ % 3 != 0 else "failed"
                        db_fixture.report_task_status(
                            queue_id,
                            task["_id"],
                            status,
                            {"result": f"success_{task['task_name']}"},
                        )

                results.append((queue_id, task_ids))
            return results

        results = benchmark.pedantic(
            queue_grouped_processing, setup=lambda: db_fixture.erase()
        )
        assert len(results) == BenchmarkConfig.NUM_QUEUES
        for queue_id, task_ids in results:
            assert len(task_ids) == BenchmarkConfig.TASKS_PER_QUEUE

    @pytest.mark.integration
    def test_queue_grouped_threadpool(
        self, benchmark, db_fixture, queue_args, get_task_args
    ):
        """Benchmark queue-grouped processing using threadpool for all database operations.

        API calls per benchmark run:
        - create_queue: {NUM_QUEUES} calls via threadpool
        - create_task: {NUM_QUEUES * TASKS_PER_QUEUE} calls via threadpool
        - fetch_task: {NUM_QUEUES * TASKS_TO_PROCESS} calls via threadpool
        - update_task_status: {NUM_QUEUES * TASKS_TO_PROCESS} calls via threadpool (mix of success/failure)

        All operations wrapped in run_in_threadpool
        """

        def queue_grouped_processing_async():
            async def _queue_grouped_processing():
                assert db_fixture.is_empty()

                run_id = uuid.uuid4().hex[:8]  # Unique ID for this benchmark run
                results = []
                # Create multiple queues with tasks
                for i in range(BenchmarkConfig.NUM_QUEUES):
                    # Create queue with unique name
                    queue_args_i = generate_unique_queue_args(
                        queue_args, f"async_{run_id}_{i}"
                    )
                    queue_id = await run_in_threadpool(
                        db_fixture.create_queue, **queue_args_i
                    )

                    # Create tasks per queue
                    task_ids = []
                    for j in range(BenchmarkConfig.TASKS_PER_QUEUE):
                        task_args = get_task_args(queue_id)
                        task_args["task_name"] = f"task_{i}_{j}"  # Unique task names
                        task_id = await run_in_threadpool(
                            db_fixture.create_task, **task_args
                        )
                        task_ids.append(task_id)

                    # Fetch and update tasks
                    for _ in range(BenchmarkConfig.TASKS_TO_PROCESS):
                        task = await run_in_threadpool(
                            db_fixture.fetch_task, queue_id=queue_id
                        )
                        if task:
                            # Update task status with random success/failure
                            status = "success" if _ % 3 != 0 else "failed"
                            await run_in_threadpool(
                                db_fixture.report_task_status,
                                queue_id,
                                task["_id"],
                                status,
                                {"result": f"success_{task['task_name']}"},
                            )

                    results.append((queue_id, task_ids))
                return results

            return asyncio.run(_queue_grouped_processing())

        results = benchmark.pedantic(
            queue_grouped_processing_async, setup=lambda: db_fixture.erase()
        )
        assert len(results) == BenchmarkConfig.NUM_QUEUES
        for queue_id, task_ids in results:
            assert len(task_ids) == BenchmarkConfig.TASKS_PER_QUEUE

    @pytest.mark.integration
    def test_operation_grouped(self, benchmark, db_fixture, queue_args, get_task_args):
        """Benchmark operation-grouped processing where similar operations are batched together.

        API calls per benchmark run:
        1. First phase - Queue creation:
           - create_queue: {NUM_QUEUES} calls in sequence

        2. Second phase - Task creation:
           - create_task: {NUM_QUEUES * TASKS_PER_QUEUE} calls in burst

        3. Third phase - Task processing:
           - fetch_task: {NUM_QUEUES * TASKS_TO_PROCESS} calls
           - update_task_status: {NUM_QUEUES * TASKS_TO_PROCESS} calls (mix of success/failure)
        """

        def operation_grouped_processing():
            assert db_fixture.is_empty()

            run_id = uuid.uuid4().hex[:8]  # Unique ID for this benchmark run
            results = {"queues": [], "tasks": [], "updates": 0}

            # First phase: Create all queues
            for i in range(BenchmarkConfig.NUM_QUEUES):
                queue_args_i = generate_unique_queue_args(
                    queue_args, f"batch_{run_id}_{i}"
                )
                queue_id = db_fixture.create_queue(**queue_args_i)
                results["queues"].append(queue_id)

            # Second phase: Create all tasks for all queues
            for queue_id in results["queues"]:
                for j in range(BenchmarkConfig.TASKS_PER_QUEUE):
                    task_args = get_task_args(queue_id)
                    task_args["task_name"] = f"batch_task_{j}"
                    task_id = db_fixture.create_task(**task_args)
                    results["tasks"].append(task_id)

            # Third phase: Process tasks
            # First fetch all tasks that will be processed
            tasks_to_update = []  # Store (queue_id, task_id) pairs
            for queue_id in results["queues"]:
                for _ in range(BenchmarkConfig.TASKS_TO_PROCESS):
                    task = db_fixture.fetch_task(queue_id=queue_id)
                    if task:
                        tasks_to_update.append((queue_id, task["_id"]))
                        results["updates"] += 1

            # Then update all fetched tasks
            for idx, (queue_id, task_id) in enumerate(tasks_to_update):
                # Report task with random success/failure
                status = "success" if idx % 3 != 0 else "failed"
                db_fixture.report_task_status(
                    queue_id, task_id, status, {"result": f"processed_{task_id}"}
                )

            return results

        results = benchmark.pedantic(
            operation_grouped_processing, setup=lambda: db_fixture.erase()
        )
        assert len(results["queues"]) == BenchmarkConfig.NUM_QUEUES
        assert (
            len(results["tasks"])
            == BenchmarkConfig.NUM_QUEUES * BenchmarkConfig.TASKS_PER_QUEUE
        )
        assert (
            results["updates"]
            == BenchmarkConfig.NUM_QUEUES * BenchmarkConfig.TASKS_TO_PROCESS
        )

    @pytest.mark.integration
    def test_operation_grouped_threadpool(
        self, benchmark, db_fixture, queue_args, get_task_args
    ):
        """Benchmark operation-grouped processing using threadpool for all database operations.

        API calls per benchmark run:
        1. First phase - Queue creation:
        - create_queue: {NUM_QUEUES} calls in sequence via threadpool

        2. Second phase - Task creation:
        - create_task: {NUM_QUEUES * TASKS_PER_QUEUE} calls in burst via threadpool

        3. Third phase - Task processing:
        - fetch_task: {NUM_QUEUES * TASKS_TO_PROCESS} calls via threadpool
        - update_task_status: {NUM_QUEUES * TASKS_TO_PROCESS} calls via threadpool (mix of success/failure)
        """

        def operation_grouped_processing_async():
            async def _operation_grouped_processing():
                assert db_fixture.is_empty()

                run_id = uuid.uuid4().hex[:8]  # Unique ID for this benchmark run
                results = {"queues": [], "tasks": [], "updates": 0}

                # First phase: Create all queues
                for i in range(BenchmarkConfig.NUM_QUEUES):
                    queue_args_i = generate_unique_queue_args(
                        queue_args, f"batch_async_{run_id}_{i}"
                    )
                    queue_id = await run_in_threadpool(
                        db_fixture.create_queue, **queue_args_i
                    )
                    results["queues"].append(queue_id)

                # Second phase: Create all tasks for all queues
                for queue_id in results["queues"]:
                    for j in range(BenchmarkConfig.TASKS_PER_QUEUE):
                        task_args = get_task_args(queue_id)
                        task_args["task_name"] = f"batch_task_{j}"
                        task_id = await run_in_threadpool(
                            db_fixture.create_task, **task_args
                        )
                        results["tasks"].append(task_id)

                # Third phase: Process tasks
                tasks_to_update = []  # Store (queue_id, task_id) pairs
                for queue_id in results["queues"]:
                    for _ in range(BenchmarkConfig.TASKS_TO_PROCESS):
                        task = await run_in_threadpool(
                            db_fixture.fetch_task, queue_id=queue_id
                        )
                        if task:
                            tasks_to_update.append((queue_id, task["_id"]))
                            results["updates"] += 1

                # Update all fetched tasks
                for idx, (queue_id, task_id) in enumerate(tasks_to_update):
                    # Alternate between success and failure
                    status = "success" if idx % 3 != 0 else "failed"
                    await run_in_threadpool(
                        db_fixture.report_task_status,
                        queue_id,
                        task_id,
                        status,
                        {"result": f"processed_{task_id}"},
                    )

                return results

            return asyncio.run(_operation_grouped_processing())

        results = benchmark.pedantic(
            operation_grouped_processing_async, setup=lambda: db_fixture.erase()
        )
        assert len(results["queues"]) == BenchmarkConfig.NUM_QUEUES
        assert (
            len(results["tasks"])
            == BenchmarkConfig.NUM_QUEUES * BenchmarkConfig.TASKS_PER_QUEUE
        )
        assert (
            results["updates"]
            == BenchmarkConfig.NUM_QUEUES * BenchmarkConfig.TASKS_TO_PROCESS
        )
