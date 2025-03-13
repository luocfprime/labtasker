import pytest
from fastapi import HTTPException
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from labtasker.server.fsm import EntityType, TaskFSM, TaskState, WorkerFSM, WorkerState


@pytest.fixture
def task_db_entry():
    """Sample task database entry. Minimal for FSM testing."""
    return {
        "_id": "test_task_id",
        "queue_id": "test_queue_id",
        "status": TaskState.PENDING,
        "retries": 0,
        "max_retries": 3,
        "metadata": {},
    }


@pytest.fixture
def worker_db_entry():
    """Sample worker database entry. Minimal for FSM testing."""
    return {
        "_id": "test_worker_id",
        "queue_id": "test_queue_id",
        "status": WorkerState.ACTIVE,
        "retries": 0,
        "max_retries": 3,
        "metadata": {},
    }


@pytest.mark.unit
class TestTaskFSM:
    def test_from_db_entry(self, task_db_entry):
        """Test creating FSM from database entry."""
        fsm = TaskFSM.from_db_entry(task_db_entry)
        assert fsm.state == TaskState.PENDING
        assert fsm.retries == 0
        assert fsm.max_retries == 3
        assert fsm.queue_id == "test_queue_id"
        assert fsm.entity_id == "test_task_id"

    def test_cancel_from_any_state(self, task_db_entry):
        """Test cancelling task from any state."""
        states = [
            TaskState.PENDING,
            TaskState.RUNNING,
            TaskState.SUCCESS,
            TaskState.FAILED,
        ]
        for state in states:
            task_db_entry["status"] = state
            fsm = TaskFSM.from_db_entry(task_db_entry)
            event_handle = fsm.cancel()
            assert fsm.state == TaskState.CANCELLED
            assert event_handle.old_state == state
            assert event_handle.new_state == TaskState.CANCELLED
            assert event_handle.entity_type == EntityType.TASK
            assert event_handle.queue_id == "test_queue_id"
            assert event_handle.entity_id == "test_task_id"

    def test_reset_from_any_state(self, task_db_entry):
        """Test resetting task from any state."""
        states = [
            TaskState.RUNNING,
            TaskState.SUCCESS,
            TaskState.FAILED,
            TaskState.CANCELLED,
        ]
        for state in states:
            task_db_entry["status"] = state
            task_db_entry["retries"] = 2
            fsm = TaskFSM.from_db_entry(task_db_entry)
            event_handle = fsm.reset()
            assert fsm.state == TaskState.PENDING
            assert fsm.retries == 0
            assert event_handle.old_state == state
            assert event_handle.new_state == TaskState.PENDING

    def test_fail_retry_behavior(self, task_db_entry):
        """Test failure and retry behavior."""
        task_db_entry["status"] = TaskState.RUNNING
        fsm = TaskFSM.from_db_entry(task_db_entry)

        # First failure should go to PENDING
        event_handle = fsm.fail()
        assert fsm.state == TaskState.PENDING
        assert fsm.retries == 1
        assert event_handle.old_state == TaskState.RUNNING
        assert event_handle.new_state == TaskState.PENDING

        # Set back to RUNNING and fail again
        fsm.force_set_state(TaskState.RUNNING)
        event_handle = fsm.fail()
        assert fsm.state == TaskState.PENDING
        assert fsm.retries == 2
        assert event_handle.old_state == TaskState.RUNNING
        assert event_handle.new_state == TaskState.PENDING

        # Third failure should go to FAILED
        fsm.force_set_state(TaskState.RUNNING)
        event_handle = fsm.fail()
        assert fsm.state == TaskState.FAILED
        assert fsm.retries == 3
        assert event_handle.old_state == TaskState.RUNNING
        assert event_handle.new_state == TaskState.FAILED


@pytest.mark.unit
class TestWorkerFSM:
    def test_from_db_entry(self, worker_db_entry):
        """Test creating FSM from database entry."""
        fsm = WorkerFSM.from_db_entry(worker_db_entry)
        assert fsm.state == WorkerState.ACTIVE
        assert fsm.retries == 0
        assert fsm.max_retries == 3
        assert fsm.queue_id == "test_queue_id"
        assert fsm.entity_id == "test_worker_id"

    def test_activate_from_any_state(self, worker_db_entry):
        """Test activating worker from any state."""
        states = [WorkerState.SUSPENDED, WorkerState.CRASHED]
        for state in states:
            worker_db_entry["status"] = state
            fsm = WorkerFSM.from_db_entry(worker_db_entry)
            event_handle = fsm.activate()
            assert fsm.state == WorkerState.ACTIVE
            assert event_handle.old_state == state
            assert event_handle.new_state == WorkerState.ACTIVE
            assert event_handle.entity_type == EntityType.WORKER

    def test_suspend_from_active(self, worker_db_entry):
        """Test suspending active worker."""
        worker_db_entry["status"] = WorkerState.ACTIVE
        fsm = WorkerFSM.from_db_entry(worker_db_entry)
        event_handle = fsm.suspend()
        assert fsm.state == WorkerState.SUSPENDED
        assert event_handle.old_state == WorkerState.ACTIVE
        assert event_handle.new_state == WorkerState.SUSPENDED
        assert event_handle.entity_type == EntityType.WORKER

    def test_suspend_from_invalid_state(self, worker_db_entry):
        """Test suspending worker from invalid state."""
        invalid_states = [WorkerState.SUSPENDED, WorkerState.CRASHED]
        for state in invalid_states:
            worker_db_entry["status"] = state
            fsm = WorkerFSM.from_db_entry(worker_db_entry)
            with pytest.raises(HTTPException) as exc:
                fsm.suspend()
            assert exc.value.status_code == HTTP_500_INTERNAL_SERVER_ERROR
            assert f"Cannot transition from {state} to suspended" in exc.value.detail

    def test_fail_retry_behavior(self, worker_db_entry):
        """Test worker failure and retry behavior."""
        worker_db_entry["status"] = WorkerState.ACTIVE
        worker_db_entry["max_retries"] = 2
        fsm = WorkerFSM.from_db_entry(worker_db_entry)

        # First failure stays ACTIVE
        event_handle = fsm.fail()
        assert fsm.state == WorkerState.ACTIVE
        assert fsm.retries == 1
        assert event_handle.old_state == WorkerState.ACTIVE
        assert event_handle.new_state == WorkerState.ACTIVE

        # Second failure goes to CRASHED
        event_handle = fsm.fail()
        assert fsm.state == WorkerState.CRASHED
        assert fsm.retries == 2
        assert event_handle.old_state == WorkerState.ACTIVE
        assert event_handle.new_state == WorkerState.CRASHED

    def test_fail_from_invalid_state(self, worker_db_entry):
        """Test failing worker from invalid state."""
        invalid_states = [WorkerState.SUSPENDED, WorkerState.CRASHED]
        for state in invalid_states:
            worker_db_entry["status"] = state
            fsm = WorkerFSM.from_db_entry(worker_db_entry)
            with pytest.raises(HTTPException) as exc:
                fsm.fail()
            assert exc.value.status_code == HTTP_500_INTERNAL_SERVER_ERROR
            assert f"Cannot fail worker in {state} state" in exc.value.detail
