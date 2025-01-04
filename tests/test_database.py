from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from labtasker.database import TaskState


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


def test_task_state_transitions(mock_db, queue_args, task_args):
    """Test task state transitions."""
    # Create queue and task
    mock_db.create_queue(**queue_args)
    task_id = mock_db.create_task(**task_args)

    # Get initial state
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.PENDING

    # Valid transitions
    assert mock_db.update_task_status(task_id, TaskState.RUNNING)
    assert mock_db.update_task_status(task_id, TaskState.COMPLETED)

    # Invalid transition (from COMPLETED to RUNNING)
    with pytest.raises(HTTPException) as exc:
        mock_db.update_task_status(task_id, TaskState.RUNNING)
    assert exc.value.status_code == 400
    assert "Cannot transition from completed to running" == exc.value.detail

    # Test that task state is unchanged after invalid transition
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.COMPLETED


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
