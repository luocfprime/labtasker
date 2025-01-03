import pytest
from fastapi import HTTPException

from labtasker.fsm import TaskFSM, TaskState


def test_valid_transitions():
    """Test all valid state transitions."""
    fsm = TaskFSM(current_state=TaskState.CREATED, retry_count=0, max_retries=2)

    # CREATED -> PENDING
    assert fsm.state == TaskState.CREATED
    fsm.validate_transition(TaskState.PENDING)
    fsm.state = TaskState.PENDING

    # PENDING -> RUNNING
    fsm.validate_transition(TaskState.RUNNING)
    fsm.state = TaskState.RUNNING

    # RUNNING -> COMPLETED
    fsm.validate_transition(TaskState.COMPLETED)
    fsm.state = TaskState.COMPLETED

    # COMPLETED -> PENDING (via reset)
    fsm.validate_transition(TaskState.PENDING)
    fsm.state = TaskState.PENDING


def test_invalid_transitions():
    """Test invalid state transitions."""
    fsm = TaskFSM(current_state=TaskState.CREATED, retry_count=0, max_retries=2)

    # Can't go directly from CREATED to RUNNING
    with pytest.raises(HTTPException) as exc:
        fsm.validate_transition(TaskState.RUNNING)
    assert "Cannot transition from created to running" == exc.value.detail

    # Can't go directly from CREATED to COMPLETED
    with pytest.raises(HTTPException) as exc:
        fsm.validate_transition(TaskState.COMPLETED)
    assert "Cannot transition from created to completed" == exc.value.detail


def test_reset_behavior():
    """Test reset functionality from different states."""
    fsm = TaskFSM(current_state=TaskState.CREATED, retry_count=0, max_retries=2)

    # Set some initial conditions
    fsm.retry_count = 2
    old_transition = fsm.last_transition

    # Reset from CREATED state
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retry_count == 0
    assert fsm.last_transition > old_transition

    # Reset from RUNNING state
    fsm.state = TaskState.RUNNING
    fsm.retry_count = 2
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retry_count == 0

    # Reset from COMPLETED state
    fsm.state = TaskState.COMPLETED
    fsm.retry_count = 2
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retry_count == 0

    # Reset from FAILED state
    fsm.state = TaskState.FAILED
    fsm.retry_count = 2
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retry_count == 0


def test_fail_retry_behavior():
    """Test failure and retry behavior."""
    fsm = TaskFSM(TaskState.CREATED, retry_count=0, max_retries=3)
    fsm.state = TaskState.RUNNING

    # First failure should go to PENDING
    fsm.fail()
    assert fsm.state == TaskState.PENDING
    assert fsm.retry_count == 1

    # Set back to RUNNING and fail again
    fsm.state = TaskState.RUNNING
    fsm.fail()
    assert fsm.state == TaskState.PENDING
    assert fsm.retry_count == 2

    # Third failure should go to FAILED
    fsm.state = TaskState.RUNNING
    fsm.fail()
    assert fsm.state == TaskState.FAILED
    assert fsm.retry_count == 3


def test_serialization():
    """Test FSM serialization and deserialization."""
    fsm = TaskFSM(TaskState.RUNNING, retry_count=2, max_retries=5)

    # Convert to dict
    data = fsm.to_dict()
    assert data["state"] == TaskState.RUNNING
    assert data["max_retries"] == 5
    assert data["retry_count"] == 2
    assert "last_transition" in data

    # Create new FSM from dict
    new_fsm = TaskFSM.from_dict(data)
    assert new_fsm.state == fsm.state
    assert new_fsm.max_retries == fsm.max_retries
    assert new_fsm.retry_count == fsm.retry_count
