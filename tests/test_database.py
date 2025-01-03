from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from labtasker.database import TaskState
from labtasker.utils import TimeControl


def test_create_queue(mock_db, queue_data):
    queue_id = mock_db.create_queue(**queue_data)
    assert queue_id is not None

    # Verify queue was created
    queue = mock_db.queues.find_one({"_id": queue_id})
    assert queue is not None
    assert queue["queue_name"] == queue_data["queue_name"]
    # Verify password is hashed and can be verified
    assert mock_db.security.verify_password(queue_data["password"], queue["password"])
    assert isinstance(queue["created_at"], datetime)


def test_submit_task(mock_db, queue_data, task_data):
    # Create queue first
    queue_id = mock_db.create_queue(**queue_data)

    # Submit task
    task_id = mock_db.submit_task(**task_data)
    assert task_id is not None

    # Verify task was created
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task is not None
    assert task["queue_id"] == queue_id
    assert task["queue_name"] == queue_data["queue_name"]
    assert task["task_name"] == task_data["task_name"]
    assert task["status"] == TaskState.CREATED
    assert task["args"] == task_data["args"]
    assert task["metadata"] == task_data["metadata"]


def test_fetch_task(mock_db, queue_data, task_data):
    # Setup
    queue_id = mock_db.create_queue(**queue_data)
    mock_db.submit_task(**task_data)

    # Fetch task
    worker_id = "test_worker"
    task = mock_db.fetch_task(
        queue_name=queue_data["queue_name"], worker_id=worker_id, eta_max="2h"
    )

    assert task is not None
    assert task["status"] == TaskState.RUNNING
    assert task["worker_metadata"]["worker_id"] == worker_id
    assert task["worker_metadata"]["status"] == "active"
    assert task["worker_metadata"]["queue_id"] == queue_id


def test_create_duplicate_queue(mock_db, queue_data, monkeypatch):
    """Test creating a queue with duplicate name."""
    # Create first queue
    mock_db.create_queue(**queue_data)

    # Try to create duplicate queue
    with pytest.raises(HTTPException) as exc_info:
        mock_db.create_queue(**queue_data)
    assert exc_info.value.status_code == 409
    assert "already exists" in exc_info.value.detail


def test_create_queue_invalid_name(mock_db):
    """Test creating a queue with invalid name."""
    with pytest.raises(HTTPException) as exc:
        mock_db.create_queue(queue_name="", password="test")
    assert exc.value.status_code == 400
    assert "Invalid queue name" in exc.value.detail


def test_submit_task_nonexistent_queue(mock_db, task_data):
    """Test submitting task to non-existent queue."""
    with pytest.raises(HTTPException) as exc:
        mock_db.submit_task(**task_data)
    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail


def test_submit_task_invalid_args(mock_db, queue_data):
    """Test submitting task with invalid arguments."""
    # Create queue first
    mock_db.create_queue(**queue_data)

    # Try to submit task with invalid args
    task_data = {
        "queue_name": queue_data["queue_name"],
        "task_name": "test_task",
        "args": "not a dict",  # Invalid args
    }
    with pytest.raises(HTTPException) as exc:
        mock_db.submit_task(**task_data)
    assert exc.value.status_code == 400
    assert "must be a dictionary" in exc.value.detail


def test_task_state_transitions(mock_db, queue_data, task_data):
    """Test task state transitions."""
    # Create queue and task
    mock_db.create_queue(**queue_data)
    task_id = mock_db.submit_task(**task_data)

    # Get initial state
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.CREATED

    # Valid transitions
    assert mock_db.update_task_status(task_id, TaskState.PENDING)
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


def test_task_retry_flow(mock_db, queue_data, task_data):
    """Test task retry flow."""
    # Create queue and task
    mock_db.create_queue(**queue_data)
    task_id = mock_db.submit_task(**task_data)

    # Task fails and is retried
    assert mock_db.update_task_status(task_id, TaskState.PENDING)
    assert mock_db.update_task_status(task_id, TaskState.RUNNING)
    assert mock_db.update_task_status(task_id, TaskState.FAILED)
    assert mock_db.update_task_status(
        task_id, TaskState.PENDING
    )  # Can retry after failure


def test_task_timeouts(mock_db, queue_data, task_data, mock_datetime: TimeControl):
    """Test task timeout handling."""
    # Create queue and task
    mock_db.create_queue(**queue_data)
    task_data.update(
        {
            "heartbeat_timeout": 60,  # 1 minute timeout
            "task_timeout": 3600,  # 1 hour timeout
        }
    )
    task_id = mock_db.submit_task(**task_data)

    # Set task to RUNNING state
    mock_db.update_task_status(task_id, TaskState.PENDING)
    mock_db.update_task_status(task_id, TaskState.RUNNING)

    # Update last_heartbeat to ensure it's set
    initial_time = mock_datetime.current_time
    mock_db.tasks.update_one(
        {"_id": task_id},
        {
            "$set": {
                "last_heartbeat": initial_time.replace(tzinfo=timezone.utc),
                "start_time": initial_time.replace(tzinfo=timezone.utc),
            }
        },
    )

    # Test heartbeat timeout
    mock_datetime.time_travel(120)  # 2 minutes later

    # Debug: Print task state before timeout check
    task_before = mock_db.tasks.find_one({"_id": task_id})
    print(f"\n=== Task State Before Timeout ===")
    print(f"Task ID: {task_id}")
    print(f"Status: {task_before['status']}")
    print(f"Last heartbeat: {task_before.get('last_heartbeat')}")
    print(f"Start time: {task_before.get('start_time')}")
    print(f"Heartbeat timeout: {task_before.get('heartbeat_timeout')}s")
    print(f"Task timeout: {task_before.get('task_timeout')}s")

    transitioned = mock_db.handle_timeouts()

    # Debug: Print task state after timeout check
    task_after = mock_db.tasks.find_one({"_id": task_id})
    print(f"\n=== Task State After Timeout ===")
    print(f"Task ID: {task_id}")
    print(f"Status: {task_after['status']}")
    print(f"Retry count: {task_after.get('retry_count')}")
    print(f"Error: {task_after.get('error')}")

    assert task_id in transitioned

    # Verify task was transitioned
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] in [
        TaskState.FAILED,
        TaskState.PENDING,
    ]  # Depends on retry count
    assert task["retry_count"] == 1
    assert task["error"] == "Task timed out"
    assert task["worker_metadata"] is None


def test_task_execution_timeout(
    mock_db, queue_data, task_data, mock_datetime: TimeControl
):
    """Test task execution timeout."""
    # Create queue and task with execution timeout
    mock_db.create_queue(**queue_data)
    task_data.update(
        {
            "task_timeout": 1800,  # 30 minute timeout
        }
    )
    task_id = mock_db.submit_task(**task_data)

    # Fetch task to set it to RUNNING with proper metadata
    task = mock_db.fetch_task(
        queue_name=queue_data["queue_name"],
        worker_id="test_worker",
    )
    assert task["_id"] == task_id

    # Fast forward past execution timeout
    mock_datetime.time_travel(3600)  # 1 hour later

    transitioned = mock_db.handle_timeouts()
    assert task_id in transitioned, f"Task {task_id} should be in {transitioned}"

    # Verify task was failed
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] in [TaskState.FAILED, TaskState.PENDING]
    assert "Task timed out" in task["error"]


def test_task_retry_on_timeout(
    mock_db, queue_data, task_data, mock_datetime: TimeControl
):
    """Test task retry behavior on timeout."""
    mock_db.create_queue(**queue_data)
    task_data.update(
        {
            "task_timeout": 60,
            "max_retries": 3,
        }
    )
    task_id = mock_db.submit_task(**task_data)

    # 1. First timeout
    # 1.1 Fetch and start task
    task = mock_db.fetch_task(
        queue_name=queue_data["queue_name"],
        worker_id="test_worker",
    )
    assert task["_id"] == task_id
    assert task["status"] == TaskState.RUNNING

    # 1.2 Fast forward past execution timeout
    mock_datetime.time_travel(61)
    mock_db.handle_timeouts()

    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.PENDING
    assert (
        task["retry_count"] == 1
    ), f"Retry count should be 1, but is {task['retry_count']}"

    # 2. Second timeout
    # 2.1 Fetch and start task
    task = mock_db.fetch_task(
        queue_name=queue_data["queue_name"],
        worker_id="test_worker",
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
    assert (
        task["retry_count"] == 2
    ), f"Retry count should be 2, but is {task['retry_count']}"

    # 3. Third timeout (Crash after 3 retries)
    # 3.1 Fetch and start task
    task = mock_db.fetch_task(
        queue_name=queue_data["queue_name"],
        worker_id="test_worker",
    )
    assert task["_id"] == task_id
    assert task["status"] == TaskState.RUNNING

    # 3.2 Fast forward past execution timeout
    mock_datetime.time_travel(61)
    mock_db.handle_timeouts()
    task = mock_db.tasks.find_one({"_id": task_id})
    assert task["status"] == TaskState.FAILED
    assert (
        task["retry_count"] == 3
    ), f"Retry count should be 3, but is {task['retry_count']}"
