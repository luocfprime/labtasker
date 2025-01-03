from datetime import datetime

import pytest
from fastapi import HTTPException

from labtasker.database import Priority, TaskState


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

    # Test retry flow
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
