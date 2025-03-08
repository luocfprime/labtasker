import pytest
from fastapi import HTTPException
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from labtasker.server.fsm import TaskFSM, TaskState, WorkerFSM, WorkerState


@pytest.fixture
def task_db_entry():
    """Sample task database entry. Minimal for FSM testing."""
    return {
        "status": TaskState.PENDING,
        "retries": 0,
        "max_retries": 3,
    }


@pytest.fixture
def worker_db_entry():
    """Sample worker database entry. Minimal for FSM testing."""
    return {
        "status": WorkerState.ACTIVE,
        "retries": 0,
        "max_retries": 3,
    }


@pytest.mark.unit
class TestTaskFSM:
    def test_from_db_entry(self, task_db_entry):
        """Test creating FSM from database entry."""
        fsm = TaskFSM.from_db_entry(task_db_entry)
        assert fsm.state == TaskState.PENDING
        assert fsm.retries == 0
        assert fsm.max_retries == 3

    def test_cancel_from_any_state(self):
        """Test cancelling task from any state."""
        states = [
            TaskState.PENDING,
            TaskState.RUNNING,
            TaskState.SUCCESS,
            TaskState.FAILED,
        ]
        for state in states:
            fsm = TaskFSM(state, retries=0, max_retries=3)
            fsm.cancel()
            assert fsm.state == TaskState.CANCELLED

    def test_reset_from_any_state(self):
        """Test resetting task from any state."""
        states = [
            TaskState.RUNNING,
            TaskState.SUCCESS,
            TaskState.FAILED,
            TaskState.CANCELLED,
        ]
        for state in states:
            fsm = TaskFSM(state, retries=2, max_retries=3)
            fsm.reset()
            assert fsm.state == TaskState.PENDING
            assert fsm.retries == 0

    def test_fail_retry_behavior(self):
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


@pytest.mark.unit
class TestWorkerFSM:
    def test_from_db_entry(self, worker_db_entry):
        """Test creating FSM from database entry."""
        fsm = WorkerFSM.from_db_entry(worker_db_entry)
        assert fsm.state == WorkerState.ACTIVE
        assert fsm.retries == 0
        assert fsm.max_retries == 3

    def test_activate_from_any_state(self):
        """Test activating worker from any state."""
        states = [WorkerState.SUSPENDED, WorkerState.CRASHED]
        for state in states:
            fsm = WorkerFSM(state, retries=0, max_retries=3)
            fsm.activate()
            assert fsm.state == WorkerState.ACTIVE

    def test_suspend_from_active(self):
        """Test suspending active worker."""
        fsm = WorkerFSM(WorkerState.ACTIVE, retries=0, max_retries=3)
        fsm.suspend()
        assert fsm.state == WorkerState.SUSPENDED

    def test_suspend_from_invalid_state(self):
        """Test suspending worker from invalid state."""
        invalid_states = [WorkerState.SUSPENDED, WorkerState.CRASHED]
        for state in invalid_states:
            fsm = WorkerFSM(state, retries=0, max_retries=3)
            with pytest.raises(HTTPException) as exc:
                fsm.suspend()
            assert exc.value.status_code == HTTP_500_INTERNAL_SERVER_ERROR
            assert f"Cannot transition from {state} to suspended" in exc.value.detail

    def test_fail_retry_behavior(self):
        """Test worker failure and retry behavior."""
        fsm = WorkerFSM(WorkerState.ACTIVE, retries=0, max_retries=2)

        # First failure stays ACTIVE
        fsm.fail()
        assert fsm.state == WorkerState.ACTIVE
        assert fsm.retries == 1

        # Second failure goes to CRASHED
        fsm.fail()
        assert fsm.state == WorkerState.CRASHED
        assert fsm.retries == 2

    def test_fail_from_invalid_state(self):
        """Test failing worker from invalid state."""
        invalid_states = [WorkerState.SUSPENDED, WorkerState.CRASHED]
        for state in invalid_states:
            fsm = WorkerFSM(state, retries=0, max_retries=3)
            with pytest.raises(HTTPException) as exc:
                fsm.fail()
            assert exc.value.status_code == HTTP_500_INTERNAL_SERVER_ERROR
            assert f"Cannot fail worker in {state} state" in exc.value.detail
