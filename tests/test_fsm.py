import pytest
from fastapi import HTTPException

from labtasker.fsm import TaskFSM, TaskState


def test_valid_transitions():
    """Test all valid state transitions."""
    fsm = TaskFSM(current_state=TaskState.PENDING, retries=0, max_retries=2)

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
    fsm = TaskFSM(current_state=TaskState.PENDING, retries=0, max_retries=2)

    # Can't go directly from PENDING to COMPLETED
    with pytest.raises(HTTPException) as exc:
        fsm.validate_transition(TaskState.COMPLETED)
    assert "Cannot transition from pending to completed" == exc.value.detail

    # Can't go directly from PENDING to FAILED
    with pytest.raises(HTTPException) as exc:
        fsm.validate_transition(TaskState.FAILED)
    assert "Cannot transition from pending to failed" == exc.value.detail


def test_reset_behavior():
    """Test reset functionality from different states."""
    fsm = TaskFSM(current_state=TaskState.PENDING, retries=0, max_retries=2)

    # Set some initial conditions
    fsm.retries = 2

    # Reset from PENDING state
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retries == 0

    # Reset from RUNNING state
    fsm.force_set_state(TaskState.RUNNING)
    fsm.retries = 2
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retries == 0

    # Reset from COMPLETED state
    fsm.force_set_state(TaskState.COMPLETED)
    fsm.retries = 2
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retries == 0

    # Reset from FAILED state
    fsm.force_set_state(TaskState.FAILED)
    fsm.retries = 2
    fsm.reset()
    assert fsm.state == TaskState.PENDING
    assert fsm.retries == 0


def test_fail_retry_behavior():
    """Test failure and retry behavior."""
    fsm = TaskFSM(TaskState.PENDING, retries=0, max_retries=3)
    fsm.state = TaskState.RUNNING

    # First failure should go to PENDING
    fsm.fail()
    assert fsm.state == TaskState.PENDING
    assert fsm.retries == 1

    # Set back to RUNNING and fail again
    fsm.state = TaskState.RUNNING
    fsm.fail()
    assert fsm.state == TaskState.PENDING
    assert fsm.retries == 2

    # Third failure should go to FAILED
    fsm.state = TaskState.RUNNING
    fsm.fail()
    assert fsm.state == TaskState.FAILED
    assert fsm.retries == 3
