from datetime import datetime, timedelta
from functools import partial

import pytest
from fastapi import HTTPException
from freezegun import freeze_time
from pymongo.collection import ReturnDocument

from labtasker.security import verify_password
from labtasker.server.database import (
    Priority,
    TaskFSM,
    TaskState,
    WorkerState,
    merge_filter,
)


@pytest.mark.integration
@pytest.mark.unit
def test_create_queue(db_fixture, queue_args):
    queue_id = db_fixture.create_queue(**queue_args)
    assert queue_id is not None

    # Verify queue was created
    queue = db_fixture._queues.find_one({"_id": queue_id})
    assert queue is not None
    assert queue["queue_name"] == queue_args["queue_name"]
    # Verify password is hashed and can be verified
    assert verify_password(queue_args["password"], queue["password"])
    assert isinstance(queue["created_at"], datetime)


@pytest.mark.integration
@pytest.mark.unit
def test_create_task(db_fixture, queue_args, get_task_args, get_full_task_args):
    # Create queue first
    queue_id = db_fixture.create_queue(**queue_args)

    # Test 1. Create task with minimal args
    task_id = db_fixture.create_task(**get_task_args(queue_id))
    assert task_id is not None

    # Verify task was created
    task = db_fixture._tasks.find_one({"_id": task_id})
    assert task is not None
    assert task["queue_id"] == queue_id
    assert task["status"] == TaskState.PENDING

    # Test 2. Create task with all args
    task_id = db_fixture.create_task(**get_full_task_args(queue_id))
    assert task_id is not None

    task = db_fixture._tasks.find_one({"_id": task_id})
    assert task is not None
    assert task["queue_id"] == queue_id
    assert task["status"] == TaskState.PENDING

    for k, v in get_full_task_args(queue_id).items():
        assert task[k] == v, f"{k} mismatch!"

    # TODO: test setting heartbeat_timeout, task_timeout, max_retries, priority


@pytest.mark.integration
@pytest.mark.unit
def test_fetch_task(db_fixture, queue_args, get_task_args):
    # Setup
    queue_id = db_fixture.create_queue(**queue_args)

    # 1. Basic fetch
    db_fixture.create_task(**get_task_args(queue_id))

    # Fetch task
    task = db_fixture.fetch_task(queue_id=queue_id)

    assert task is not None
    assert task["status"] == TaskState.RUNNING


@pytest.mark.integration
@pytest.mark.unit
def test_create_duplicate_queue(db_fixture, queue_args, monkeypatch):
    """Test creating a queue with duplicate name."""
    # Create first queue
    db_fixture.create_queue(**queue_args)

    # Try to create duplicate queue
    with pytest.raises(HTTPException) as exc_info:
        db_fixture.create_queue(**queue_args)
    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail


@pytest.mark.integration
@pytest.mark.unit
def test_create_queue_invalid_name(db_fixture):
    """Test creating a queue with invalid name."""
    with pytest.raises(HTTPException) as exc:
        db_fixture.create_queue(queue_name="", password="test")
    assert exc.value.status_code == 400
    assert "Queue name is required" in exc.value.detail


@pytest.mark.integration
@pytest.mark.unit
def test_create_task_invalid_args(db_fixture, queue_args):
    """Test submitting task with invalid arguments."""
    # Create queue first
    queue_id = db_fixture.create_queue(**queue_args)

    # Try to submit task with invalid args
    task_data = {
        "queue_id": queue_id,
        "task_name": "test_task",
        "args": "not a dict",  # Invalid args
    }
    with pytest.raises(HTTPException) as exc:
        db_fixture.create_task(**task_data)
    assert exc.value.status_code == 400
    assert "must be a dictionary" in exc.value.detail


@pytest.mark.integration
@pytest.mark.unit
def test_heartbeat_timeout(db_fixture, queue_args, get_task_args):
    """Test task execution timeout using freezegun."""
    # Create queue and task with a heartbeat timeout
    queue_id = db_fixture.create_queue(**queue_args)
    task_id = db_fixture.create_task(
        **get_task_args(
            queue_id,
            override_fields={
                "heartbeat_timeout": 120,  # 2-minute timeout
                "max_retries": 1,
            },
        )
    )

    # Freeze time
    with freeze_time("2025-01-01 12:00:00") as frozen_time:
        # Fetch the task to set it to RUNNING and initialize metadata
        task = db_fixture.fetch_task(
            queue_id=queue_id,
        )
        assert task["_id"] == task_id

        # Fast-forward time beyond the heartbeat timeout
        frozen_time.tick(timedelta(seconds=121))  # Move forward 2 minutes and 1 second
        transitioned = db_fixture.handle_timeouts()
        assert task_id in transitioned, f"Task {task_id} should be in {transitioned}"

        # Verify the task was marked as FAILED
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task["status"] == TaskState.FAILED
        assert (
            task["retries"] == 1
        ), f"Retry count should be 1, but is {task['retries']}"
        assert "timed out" in task["summary"]["labtasker_error"]


@pytest.mark.integration
@pytest.mark.unit
def test_task_retry_on_timeout(db_fixture, queue_args, get_task_args):
    """Test task retry behavior on timeout using freezegun."""
    # Create queue and task with a timeout and max retries
    queue_id = db_fixture.create_queue(**queue_args)

    task_id = db_fixture.create_task(
        **get_task_args(
            queue_id,
            override_fields={
                "task_timeout": 60,  # 1-minute timeout
                "max_retries": 3,
            },
        )
    )

    # Freeze time at a specific starting point
    with freeze_time("2025-01-01 12:00:00") as frozen_time:
        # 1. First timeout
        # 1.1 Fetch and start the task
        task = db_fixture.fetch_task(
            queue_id=queue_id,
        )
        assert task["_id"] == task_id
        assert task["status"] == TaskState.RUNNING

        # 1.2 Fast forward past the task timeout
        frozen_time.tick(timedelta(seconds=61))  # Move forward 61 seconds
        db_fixture.handle_timeouts()

        # Verify the task is set to PENDING and retry count is updated
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task["status"] == TaskState.PENDING
        assert (
            task["retries"] == 1
        ), f"Retry count should be 1, but is {task['retries']}"

        # 2. Second timeout
        # 2.1 Fetch and start the task again
        task = db_fixture.fetch_task(
            queue_id=queue_id,
        )
        assert task["_id"] == task_id
        assert task["status"] == TaskState.RUNNING

        # 2.2 Fast forward by half of the timeout duration
        frozen_time.tick(timedelta(seconds=30))  # Move forward 30 seconds
        db_fixture.handle_timeouts()

        # Verify the task is still RUNNING, as the timeout has not yet elapsed
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert (
            task["status"] == TaskState.RUNNING
        ), f"Task status should be RUNNING, since it's only half of the timeout"

        # 2.3 Fast forward past the remaining timeout duration
        frozen_time.tick(timedelta(seconds=31))  # Move forward 31 seconds
        db_fixture.handle_timeouts()

        # Verify the task is set to PENDING again and retry count is updated
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task["status"] == TaskState.PENDING
        assert (
            task["retries"] == 2
        ), f"Retry count should be 2, but is {task['retries']}"

        # 3. Third timeout (Task fails after reaching max retries)
        # 3.1 Fetch and start the task again
        task = db_fixture.fetch_task(
            queue_id=queue_id,
        )
        assert task["_id"] == task_id
        assert task["status"] == TaskState.RUNNING

        # 3.2 Fast forward past the task timeout
        frozen_time.tick(timedelta(seconds=61))  # Move forward 61 seconds
        db_fixture.handle_timeouts()

        # Verify the task is set to FAILED after exceeding max retries
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task["status"] == TaskState.FAILED
        assert (
            task["retries"] == 3
        ), f"Retry count should be 3, but is {task['retries']}"


@pytest.mark.integration
@pytest.mark.unit
def test_update_task_status(db_fixture, queue_args, get_task_args):
    """Test task status updates."""
    # Setup: Create queue and task
    queue_id = db_fixture.create_queue(**queue_args)

    # Test case 1: Success path
    task_id = db_fixture.create_task(**get_task_args(queue_id))
    task = db_fixture.fetch_task(queue_id=queue_id)
    assert task["status"] == TaskState.RUNNING
    assert task["_id"] == task_id
    assert db_fixture.update_task_status(
        queue_id, task_id, "success", {"result": "test passed"}
    )
    task = db_fixture._tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.COMPLETED
    assert task["summary"]["result"] == "test passed"

    # Test case 2: Failed with retry
    task_id = db_fixture.create_task(**get_task_args(queue_id))  # Create new task
    task = db_fixture.fetch_task(queue_id=queue_id)
    assert task["_id"] == task_id
    assert db_fixture.update_task_status(queue_id, task_id, "failed")
    task = db_fixture._tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.PENDING  # First failure goes to PENDING
    assert task["retries"] == 1

    # Test case 3: Failed after max retries
    for _ in range(2):  # Already has 1 retry, need 2 more to reach max
        task = db_fixture.fetch_task(queue_id=queue_id)
        assert task["_id"] == task_id
        assert db_fixture.update_task_status(queue_id, task_id, "failed")
    task = db_fixture._tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.FAILED
    assert task["retries"] == 3

    # Test case 4: Cancel task from PENDING
    task_id = db_fixture.create_task(**get_task_args(queue_id))
    assert db_fixture.update_task_status(queue_id, task_id, "cancelled")
    task = db_fixture._tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.CANCELLED

    # Test case 5: Cancel task from RUNNING
    task_id = db_fixture.create_task(**get_task_args(queue_id))
    task = db_fixture.fetch_task(queue_id=queue_id)
    assert task["_id"] == task_id
    assert db_fixture.update_task_status(queue_id, task_id, "cancelled")
    task = db_fixture._tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.CANCELLED

    # Test case 6: Invalid status
    with pytest.raises(HTTPException) as exc:
        db_fixture.update_task_status(queue_id, task_id, "invalid_status")
    assert exc.value.status_code == 400
    assert "Invalid report_status" in exc.value.detail

    # # Test case 7: Non-existent queue (deprecated. 404 is handled by server, not DB)
    # with pytest.raises(HTTPException) as exc:
    #     db_fixture.update_task_status("non_existent_queue", task_id, "success")
    # assert exc.value.status_code == 404
    # assert "Queue 'non_existent_queue' not found" in exc.value.detail

    # Test case 8: Non-existent task
    with pytest.raises(HTTPException) as exc:
        db_fixture.update_task_status(queue_id, "non_existent_task", "success")
    assert exc.value.status_code == 404
    assert "Task non_existent_task not found" in exc.value.detail


@pytest.mark.integration
@pytest.mark.unit
def test_task_fsm_consistency(db_fixture, queue_args, get_task_args):
    """Test if DB FSM logic is consistent with defined FSM logic."""
    queue_id = db_fixture.create_queue(**queue_args)

    # 1. Prepare pairs, so we can check if the FSM logic is consistent between
    #    DB and FSM.
    # event name: (initial_state, db_func, fsm_func)
    event_mapping = {
        "fetch": (
            TaskState.PENDING,
            lambda queue_id, task_id: db_fixture.fetch_task(queue_id=queue_id),
            TaskFSM.fetch,
        ),
        "report_success": (
            TaskState.RUNNING,
            partial(db_fixture.update_task_status, report_status="success"),
            TaskFSM.complete,
        ),
        "report_failed": (
            TaskState.RUNNING,
            partial(db_fixture.update_task_status, report_status="failed"),
            TaskFSM.fail,
        ),
        "report_pending_cancelled": (
            TaskState.PENDING,
            partial(db_fixture.update_task_status, report_status="cancelled"),
            TaskFSM.cancel,
        ),
        "report_running_cancelled": (
            TaskState.RUNNING,
            partial(db_fixture.update_task_status, report_status="cancelled"),
            TaskFSM.cancel,
        ),
        "report_failed_cancelled": (
            TaskState.FAILED,
            partial(db_fixture.update_task_status, report_status="cancelled"),
            TaskFSM.cancel,
        ),
        "reset_pending": (
            TaskState.PENDING,
            db_fixture.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_running": (
            TaskState.RUNNING,
            db_fixture.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_failed": (
            TaskState.FAILED,
            db_fixture.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_completed": (
            TaskState.COMPLETED,
            db_fixture.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_cancelled": (
            TaskState.CANCELLED,
            db_fixture.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
    }

    # 2. Prepare functions to get task and db_fixture in different initial states for testing

    def clear_tasks():
        db_fixture._tasks.delete_many({})

    def get_pending():
        task_id = db_fixture.create_task(**get_task_args(queue_id))
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task["status"] == TaskState.PENDING
        return task, db_fixture

    def get_running():
        task, db_fixture = get_pending()
        task = db_fixture.fetch_task(queue_id=queue_id)
        assert task["status"] == TaskState.RUNNING
        return task, db_fixture

    def get_failed():
        task_id = db_fixture.create_task(**get_task_args(queue_id))
        task = db_fixture._tasks.find_one_and_update(
            {"_id": task_id},
            {"$set": {"status": TaskState.FAILED}},
            return_document=ReturnDocument.AFTER,
        )
        assert task is not None
        return task, db_fixture

    def get_cancelled():
        task_id = db_fixture.create_task(**get_task_args(queue_id))
        task = db_fixture._tasks.find_one_and_update(
            {"_id": task_id},
            {"$set": {"status": TaskState.CANCELLED}},
            return_document=ReturnDocument.AFTER,
        )
        assert task is not None
        return task, db_fixture

    def get_completed():
        task_id = db_fixture.create_task(**get_task_args(queue_id))
        task = db_fixture._tasks.find_one_and_update(
            {"_id": task_id},
            {"$set": {"status": TaskState.COMPLETED}},
            return_document=ReturnDocument.AFTER,
        )
        assert task is not None
        return task, db_fixture

    get_initial_state_func = {
        TaskState.PENDING: get_pending,
        TaskState.RUNNING: get_running,
        TaskState.FAILED: get_failed,
        TaskState.COMPLETED: get_completed,
        TaskState.CANCELLED: get_cancelled,
    }

    # 3. Test each event, match the after state of each event
    for event_name, (init_state, db_func, fsm_func) in event_mapping.items():
        # Fetch task
        task, db_fixture = get_initial_state_func[init_state]()
        task_id = task["_id"]

        fsm = TaskFSM.from_db_entry(task)

        # FSM transition
        fsm_func(fsm)

        # Verify state after DB update
        db_func(queue_id=queue_id, task_id=task_id)
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert (
            task["status"] == fsm.state
        ), f"FSM state {fsm.state} does not match DB state {task['status']} during {event_name} event"

        # Clear tasks
        clear_tasks()


@pytest.mark.integration
@pytest.mark.unit
def test_worker_crash_no_dispatch(db_fixture, queue_args, get_task_args):
    """Test that crashed workers don't receive new tasks."""
    # Setup
    queue_id = db_fixture.create_queue(**queue_args)

    # Create worker
    worker_id = db_fixture.create_worker(
        queue_id=queue_id,
        max_retries=3,
    )

    # Create multiple tasks
    task_ids = []
    for i in range(3):
        task_ids.append(
            db_fixture.create_task(
                **get_task_args(queue_id, override_fields={"task_name": f"task_{i}"})
            )
        )

    # Simulate task failures until worker crashes
    for _ in range(3):  # Worker max_retries is 3 by default
        # Verify worker is still active
        worker = db_fixture._workers.find_one({"_id": worker_id})
        assert worker["status"] == WorkerState.ACTIVE

        # Fetch task
        task = db_fixture.fetch_task(queue_id=queue_id, worker_id=worker_id)
        assert task is not None

        # Fail task
        db_fixture.update_task_status(
            queue_id=queue_id,
            task_id=task["_id"],
            report_status="failed",
        )

    # Verify worker is now crashed
    worker = db_fixture._workers.find_one({"_id": worker_id})
    assert worker["status"] == WorkerState.CRASHED

    # Try to fetch another task
    with pytest.raises(HTTPException) as exc:
        db_fixture.fetch_task(queue_id=queue_id, worker_id=worker_id)
    assert exc.value.status_code == 400
    assert "crashed" in exc.value.detail

    # Re-activate worker
    db_fixture.update_worker_status(
        queue_id=queue_id, worker_id=worker_id, report_status="active"
    )

    # Verify worker is active
    worker = db_fixture._workers.find_one({"_id": worker_id})
    assert worker["status"] == WorkerState.ACTIVE

    # Try to fetch another task
    task = db_fixture.fetch_task(queue_id=queue_id, worker_id=worker_id)
    assert task is not None
    assert task["worker_id"] == worker_id


@pytest.mark.integration
@pytest.mark.unit
def test_worker_suspended_no_dispatch(db_fixture, queue_args, get_task_args):
    """Test that suspended workers don't receive new tasks."""
    # Setup
    queue_id = db_fixture.create_queue(**queue_args)

    # Create worker
    worker_id = db_fixture.create_worker(queue_id=queue_id)

    # Create task
    task_id = db_fixture.create_task(**get_task_args(queue_id))

    # Suspend worker
    db_fixture.update_worker_status(
        queue_id=queue_id,
        worker_id=worker_id,
        report_status="suspended",
    )

    # Verify worker is suspended
    worker = db_fixture._workers.find_one({"_id": worker_id})
    assert worker["status"] == WorkerState.SUSPENDED

    # Try to fetch task
    with pytest.raises(HTTPException) as exc:
        db_fixture.fetch_task(queue_id=queue_id, worker_id=worker_id)
    assert exc.value.status_code == 400
    assert "suspended" in exc.value.detail

    # Re-activate worker
    db_fixture.update_worker_status(
        queue_id=queue_id, worker_id=worker_id, report_status="active"
    )

    # Verify worker is active
    worker = db_fixture._workers.find_one({"_id": worker_id})
    assert worker["status"] == WorkerState.ACTIVE


@pytest.mark.integration
@pytest.mark.unit
def test_fetch_priority(db_fixture, queue_args):
    # Setup: Create a queue
    queue_id = db_fixture.create_queue(**queue_args)

    # Create tasks with different priorities
    task_args_high = {
        "queue_id": queue_id,
        "task_name": "high_priority_task",
        "args": {},
        "priority": Priority.HIGH,  # High priority
    }
    task_args_medium_1 = {
        "queue_id": queue_id,
        "task_name": "medium_priority_task_1",
        "args": {},
        "priority": Priority.MEDIUM,  # Medium priority
    }
    task_args_medium_2 = {
        "queue_id": queue_id,
        "task_name": "medium_priority_task_2",
        "args": {},
        "priority": Priority.MEDIUM,  # Medium priority
    }
    task_args_low = {
        "queue_id": queue_id,
        "task_name": "low_priority_task",
        "args": {},
        "priority": Priority.LOW,  # Low priority
    }

    # Create tasks
    db_fixture.create_task(**task_args_high)
    db_fixture.create_task(**task_args_medium_1)
    db_fixture.create_task(**task_args_medium_2)
    db_fixture.create_task(**task_args_low)

    task = db_fixture.fetch_task(queue_id=queue_id)

    # Assert that the task fetched is the one with the highest priority
    assert task is not None
    assert task["task_name"] == "high_priority_task"
    assert (
        task["priority"] == Priority.HIGH
    )  # Ensure the fetched task has the highest priority

    # Fetch again, this time should follow FIFO
    task = db_fixture.fetch_task(queue_id=queue_id)

    assert task is not None
    assert task["task_name"] == "medium_priority_task_1"


@pytest.mark.integration
@pytest.mark.unit
def test_fetch_extra_filter(db_fixture, queue_args):
    # Setup: Create a queue
    queue_id = db_fixture.create_queue(**queue_args)

    # Create tasks with different attributes
    task_args_1 = {
        "queue_id": queue_id,
        "task_name": "task_a",
        "args": {},
        "priority": Priority.HIGH,
        "metadata": {"tag": "a"},
    }
    task_args_2 = {
        "queue_id": queue_id,
        "task_name": "task_b",
        "args": {},
        "priority": Priority.MEDIUM,
        "metadata": {"tag": "b"},
    }
    task_args_3 = {
        "queue_id": queue_id,
        "task_name": "task_c",
        "args": {},
        "priority": Priority.LOW,
        "metadata": {"tag": "c"},
    }

    # Create tasks
    db_fixture.create_task(**task_args_1)
    db_fixture.create_task(**task_args_2)
    db_fixture.create_task(**task_args_3)

    # Test 1. query by self-defined tag
    extra_filter = {"metadata": {"tag": "b"}}

    task = db_fixture.fetch_task(queue_id=queue_id, extra_filter=extra_filter)

    assert task is not None
    assert task["task_name"] == "task_b"

    # Test 2. query non-existent tag
    extra_filter = {"metadata": {"tag": "no-exist"}}

    task = db_fixture.fetch_task(queue_id=queue_id, extra_filter=extra_filter)

    assert task is None  # no match


@pytest.mark.integration
@pytest.mark.unit
class TestTaskRequiredFieldFetching:
    """Tests for task fetching based on required fields."""

    def test_fetch_leaf_match(self, db_fixture, queue_args):
        """Test fetching a task with a full leaf match of required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_leaf_match",
                "args": {"arg1": "value1", "arg2": {"arg21": 1, "arg22": 2}},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_partial_match",
                "args": {"arg1": "value1"},
                "priority": Priority.MEDIUM,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = {"arg1": None, "arg2": {"arg21": None, "arg22": None}}

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is not None
        assert task["task_name"] == "task_leaf_match"

    def test_fetch_non_leaf_match(self, db_fixture, queue_args):
        """Test fetching a task with a non-leaf node match of required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_1",
                "args": {"arg1": "value1", "arg2": {"arg21": 1, "arg22": 2}},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_2",
                "args": {"arg1": "value1"},
                "priority": Priority.MEDIUM,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = {"arg1": None, "arg2": None}

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is not None
        assert task["task_name"] == "task_1"

    def test_fetch_no_match(self, db_fixture, queue_args):
        """Test fetching a task with no matching required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_no_match",
                "args": {"arg2": {"arg21": 1}},
                "priority": Priority.LOW,
            }
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = {"arg1": None}

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is None

    def test_fetch_with_multiple_matches(self, db_fixture, queue_args):
        """Test fetching tasks when multiple tasks match the required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_match_1",
                "args": {"arg1": "value1", "arg2": {"arg21": 1}},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_match_2",
                "args": {"arg1": "value1", "arg2": {"arg21": 1}},
                "priority": Priority.HIGH,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = {"arg1": None, "arg2": {"arg21": None}}

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is not None
        # Check if it fetched the one with the highest priority
        assert task["task_name"] == "task_match_2"


@pytest.mark.unit
def test_merge_filter():
    # Test 1: Merge with $and (no empty filters)
    filter1 = {"field1": {"$gt": 10}}
    filter2 = {"field2": "value"}
    filter3 = {"field3": {"$lt": 5}}
    result = merge_filter(filter1, filter2, filter3, logical_op="and")
    assert result == {
        "$and": [{"field1": {"$gt": 10}}, {"field2": "value"}, {"field3": {"$lt": 5}}]
    }, f"Test 1 failed: {result}"

    # Test 2: Merge with $or (ignoring empty filters)
    empty_filter = {}
    none_filter = None
    result = merge_filter(filter1, empty_filter, none_filter, filter3, logical_op="or")
    assert result == {
        "$or": [{"field1": {"$gt": 10}}, {"field3": {"$lt": 5}}]
    }, f"Test 2 failed: {result}"

    # Test 3: Merge with a single filter (returns the filter directly)
    result = merge_filter(filter1, empty_filter, logical_op="and")
    assert result == {"field1": {"$gt": 10}}, f"Test 3 failed: {result}"

    # Test 4: Merge with all filters empty (returns an empty filter)
    result = merge_filter(empty_filter, none_filter, logical_op="and")
    assert result == {}, f"Test 4 failed: {result}"

    # Test 5: Invalid logical operator
    try:
        merge_filter(filter1, filter2, logical_op="invalid_op")
        raise AssertionError("Test 5 failed: Did not raise HTTPException")
    except HTTPException as e:
        assert e.status_code == 500
        assert "Invalid logical operator" in e.detail, f"Test 5 failed: {e.detail}"

    # Test 6: Merge with $nor
    result = merge_filter(filter1, filter3, logical_op="nor")
    assert result == {
        "$nor": [{"field1": {"$gt": 10}}, {"field3": {"$lt": 5}}]
    }, f"Test 6 failed: {result}"

    # Test 7: No filters provided
    result = merge_filter(logical_op="and")
    assert result == {}, f"Test 7 failed: {result}"

    # Test 8: Only empty filters provided
    result = merge_filter(empty_filter, none_filter, {}, logical_op="or")
    assert result == {}, f"Test 8 failed: {result}"
