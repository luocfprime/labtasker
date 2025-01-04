from datetime import datetime, timedelta, timezone
from functools import partial

import pytest
from fastapi import HTTPException
from pymongo.collection import ReturnDocument

from labtasker.database import TaskFSM, TaskState


def test_create_queue(mock_db, queue_args):
    queue_id = mock_db.create_queue(**queue_args)
    assert queue_id is not None

    # Verify queue was created
    queue = mock_db.queues.find_one({"_id": queue_id})
    assert queue is not None
    assert queue["queue_name"] == queue_args["queue_name"]
    # Verify password is hashed and can be verified
    assert mock_db.security.verify_password(queue_args["password"], queue["password"])
    assert isinstance(queue["created_at"], datetime)


def test_create_task(mock_db, queue_args, task_args):
    # Create queue first
    queue_id = mock_db.create_queue(**queue_args)

    # Submit task
    task_id = mock_db.create_task(**task_args)
    assert task_id is not None

    # Verify task was created
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task is not None
    assert task["queue_id"] == queue_id
    assert task["task_name"] == task_args["task_name"]
    assert task["status"] == TaskState.PENDING
    assert task["args"] == task_args["args"]
    assert task["metadata"] == task_args["metadata"]

    # TODO: test settingheartbeat_timeout, task_timeout, max_retries, priority


def test_fetch_task(mock_db, queue_args, task_args):
    # Setup
    mock_db.create_queue(**queue_args)

    # 1. Basic fetch
    mock_db.create_task(**task_args)

    # Fetch task
    task = mock_db.fetch_task(queue_name=queue_args["queue_name"])

    assert task is not None
    assert task["status"] == TaskState.RUNNING


def test_create_duplicate_queue(mock_db, queue_args, monkeypatch):
    """Test creating a queue with duplicate name."""
    # Create first queue
    mock_db.create_queue(**queue_args)

    # Try to create duplicate queue
    with pytest.raises(HTTPException) as exc_info:
        mock_db.create_queue(**queue_args)
    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail


def test_create_queue_invalid_name(mock_db):
    """Test creating a queue with invalid name."""
    with pytest.raises(HTTPException) as exc:
        mock_db.create_queue(queue_name="", password="test")
    assert exc.value.status_code == 400
    assert "Invalid queue name" in exc.value.detail


def test_create_task_nonexistent_queue(mock_db, task_args):
    """Test submitting task to non-existent queue."""
    with pytest.raises(HTTPException) as exc:
        mock_db.create_task(**task_args)
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail


def test_create_task_invalid_args(mock_db, queue_args):
    """Test submitting task with invalid arguments."""
    # Create queue first
    mock_db.create_queue(**queue_args)

    # Try to submit task with invalid args
    task_data = {
        "queue_name": queue_args["queue_name"],
        "task_name": "test_task",
        "args": "not a dict",  # Invalid args
    }
    with pytest.raises(HTTPException) as exc:
        mock_db.create_task(**task_data)
    assert exc.value.status_code == 400
    assert "must be a dictionary" in exc.value.detail


def test_heartbeat_timeout(mock_db, queue_args, task_args, mock_datetime):
    """Test task execution timeout."""
    # Create queue and task with execution timeout
    mock_db.create_queue(**queue_args)
    task_args.update(
        {
            "heartbeat_timeout": 120,  # 2 minute timeout
            "max_retries": 1,
        }
    )
    task_id = mock_db.create_task(**task_args)

    # Fetch task to set it to RUNNING with proper metadata
    task = mock_db.fetch_task(
        queue_name=queue_args["queue_name"],
    )
    assert task["_id"] == task_id

    # Fast forward past execution timeout
    mock_datetime.time_travel(121)  # 2min 1sec
    transitioned = mock_db.handle_timeouts()
    assert task_id in transitioned, f"Task {task_id} should be in {transitioned}"

    # Verify task was failed
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.FAILED
    assert task["retries"] == 1, f"Retry count should be 1, but is {task['retries']}"
    assert "timed out" in task["summary"]["labtasker_error"]


def test_task_retry_on_timeout(mock_db, queue_args, task_args, mock_datetime):
    """Test task retry behavior on timeout."""
    mock_db.create_queue(**queue_args)
    task_args.update(
        {
            "task_timeout": 60,
            "max_retries": 3,
        }
    )
    task_id = mock_db.create_task(**task_args)

    # 1. First timeout
    # 1.1 Fetch and start task
    task = mock_db.fetch_task(
        queue_name=queue_args["queue_name"],
    )
    assert task["_id"] == task_id
    assert task["status"] == TaskState.RUNNING

    # 1.2 Fast forward past execution timeout
    mock_datetime.time_travel(61)
    mock_db.handle_timeouts()

    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.PENDING
    assert task["retries"] == 1, f"Retry count should be 1, but is {task['retries']}"

    # 2. Second timeout
    # 2.1 Fetch and start task
    task = mock_db.fetch_task(
        queue_name=queue_args["queue_name"],
    )
    assert task["_id"] == task_id
    assert task["status"] == TaskState.RUNNING

    # 2.2 Fast forward half of the timeout
    mock_datetime.time_travel(30)
    mock_db.handle_timeouts()
    task = mock_db.tasks.find_one({"_id": task_id})
    assert (
        task["status"] == TaskState.RUNNING
    ), f"Task status should be RUNNING, since it's only half of the timeout"

    # 2.3 Fast forward past execution timeout
    mock_datetime.time_travel(31)
    mock_db.handle_timeouts()
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.PENDING
    assert task["retries"] == 2, f"Retry count should be 2, but is {task['retries']}"

    # 3. Third timeout (Crash after 3 retries)
    # 3.1 Fetch and start task
    task = mock_db.fetch_task(
        queue_name=queue_args["queue_name"],
    )
    assert task["_id"] == task_id
    assert task["status"] == TaskState.RUNNING

    # 3.2 Fast forward past execution timeout
    mock_datetime.time_travel(61)
    mock_db.handle_timeouts()
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.FAILED
    assert task["retries"] == 3, f"Retry count should be 3, but is {task['retries']}"


def test_update_task_status(mock_db, queue_args, task_args):
    """Test task status updates."""
    # Setup: Create queue and task
    mock_db.create_queue(**queue_args)

    # Test case 1: Success path
    task_id = mock_db.create_task(**task_args)
    task = mock_db.fetch_task(queue_name=queue_args["queue_name"])
    assert task["status"] == TaskState.RUNNING
    assert task["_id"] == task_id
    assert mock_db.update_task_status(
        queue_args["queue_name"], task_id, "success", {"result": "test passed"}
    )
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.COMPLETED
    assert task["summary"]["result"] == "test passed"

    # Test case 2: Failed with retry
    task_id = mock_db.create_task(**task_args)  # Create new task
    task = mock_db.fetch_task(queue_name=queue_args["queue_name"])
    assert task["_id"] == task_id
    assert mock_db.update_task_status(queue_args["queue_name"], task_id, "failed")
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.PENDING  # First failure goes to PENDING
    assert task["retries"] == 1

    # Test case 3: Failed after max retries
    for _ in range(2):  # Already has 1 retry, need 2 more to reach max
        task = mock_db.fetch_task(queue_name=queue_args["queue_name"])
        assert task["_id"] == task_id
        assert mock_db.update_task_status(queue_args["queue_name"], task_id, "failed")
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.FAILED
    assert task["retries"] == 3

    # Test case 4: Cancel task from PENDING
    task_id = mock_db.create_task(**task_args)
    assert mock_db.update_task_status(queue_args["queue_name"], task_id, "cancelled")
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.CANCELLED

    # Test case 5: Cancel task from RUNNING
    task_id = mock_db.create_task(**task_args)
    task = mock_db.fetch_task(queue_name=queue_args["queue_name"])
    assert task["_id"] == task_id
    assert mock_db.update_task_status(queue_args["queue_name"], task_id, "cancelled")
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.CANCELLED

    # Test case 6: Invalid status
    with pytest.raises(HTTPException) as exc:
        mock_db.update_task_status(queue_args["queue_name"], task_id, "invalid_status")
    assert exc.value.status_code == 400
    assert "Invalid report_status" in exc.value.detail

    # Test case 7: Non-existent queue
    with pytest.raises(HTTPException) as exc:
        mock_db.update_task_status("non_existent_queue", task_id, "success")
    assert exc.value.status_code == 404
    assert "Queue 'non_existent_queue' not found" in exc.value.detail

    # Test case 8: Non-existent task
    with pytest.raises(HTTPException) as exc:
        mock_db.update_task_status(
            queue_args["queue_name"], "non_existent_task", "success"
        )
    assert exc.value.status_code == 404
    assert "Task non_existent_task not found" in exc.value.detail


def test_task_fsm_consistency(mock_db, queue_args, task_args):
    """Test if DB FSM logic is consistent with defined FSM logic."""
    mock_db.create_queue(**queue_args)

    # 1. Prepare pairs, so we can check if the FSM logic is consistent between
    #    DB and FSM.
    # event name: (initial_state, db_func, fsm_func)
    event_mapping = {
        "fetch": (
            TaskState.PENDING,
            lambda queue_name, task_id: mock_db.fetch_task(queue_name=queue_name),
            TaskFSM.fetch,
        ),
        "report_success": (
            TaskState.RUNNING,
            partial(mock_db.update_task_status, report_status="success"),
            TaskFSM.complete,
        ),
        "report_failed": (
            TaskState.RUNNING,
            partial(mock_db.update_task_status, report_status="failed"),
            TaskFSM.fail,
        ),
        "report_pending_cancelled": (
            TaskState.PENDING,
            partial(mock_db.update_task_status, report_status="cancelled"),
            TaskFSM.cancel,
        ),
        "report_running_cancelled": (
            TaskState.RUNNING,
            partial(mock_db.update_task_status, report_status="cancelled"),
            TaskFSM.cancel,
        ),
        "report_failed_cancelled": (
            TaskState.FAILED,
            partial(mock_db.update_task_status, report_status="cancelled"),
            TaskFSM.cancel,
        ),
        "reset_pending": (
            TaskState.PENDING,
            mock_db.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_running": (
            TaskState.RUNNING,
            mock_db.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_failed": (
            TaskState.FAILED,
            mock_db.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_completed": (
            TaskState.COMPLETED,
            mock_db.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
        "reset_cancelled": (
            TaskState.CANCELLED,
            mock_db.update_task_and_reset_pending,
            TaskFSM.reset,
        ),
    }

    # 2. Prepare functions to get task and mock_db in different initial states for testing

    def clear_tasks():
        mock_db.tasks.delete_many({})

    def get_pending():
        task_id = mock_db.create_task(**task_args)
        task = mock_db.tasks.find_one({"_id": task_id})
        assert task["status"] == TaskState.PENDING
        return task, mock_db

    def get_running():
        task, mock_db = get_pending()
        task = mock_db.fetch_task(queue_name=queue_args["queue_name"])
        assert task["status"] == TaskState.RUNNING
        return task, mock_db

    def get_failed():
        task_id = mock_db.create_task(**task_args)
        task = mock_db.tasks.find_one_and_update(
            {"_id": task_id},
            {"$set": {"status": TaskState.FAILED}},
            return_document=ReturnDocument.AFTER,
        )
        assert task is not None
        return task, mock_db

    def get_cancelled():
        task_id = mock_db.create_task(**task_args)
        task = mock_db.tasks.find_one_and_update(
            {"_id": task_id},
            {"$set": {"status": TaskState.CANCELLED}},
            return_document=ReturnDocument.AFTER,
        )
        assert task is not None
        return task, mock_db

    def get_completed():
        task_id = mock_db.create_task(**task_args)
        task = mock_db.tasks.find_one_and_update(
            {"_id": task_id},
            {"$set": {"status": TaskState.COMPLETED}},
            return_document=ReturnDocument.AFTER,
        )
        assert task is not None
        return task, mock_db

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
        task, mock_db = get_initial_state_func[init_state]()
        task_id = task["_id"]

        fsm = TaskFSM.from_db_entry(task)

        # FSM transition
        fsm_func(fsm)

        # Verify state after DB update
        db_func(queue_name=queue_args["queue_name"], task_id=task_id)
        task = mock_db.tasks.find_one({"_id": task_id})
        assert (
            task["status"] == fsm.state
        ), f"FSM state {fsm.state} does not match DB state {task['status']} during {event_name} event"

        # Clear tasks
        clear_tasks()
