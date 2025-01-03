from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from fastapi import HTTPException


class TaskState(str, Enum):
    CREATED = "created"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskFSM:
    # Define valid state transitions
    VALID_TRANSITIONS = {
        TaskState.CREATED: {TaskState.PENDING},  # Initial state can only go to PENDING
        TaskState.PENDING: {TaskState.RUNNING, TaskState.PENDING},
        TaskState.RUNNING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.PENDING},
        TaskState.COMPLETED: {TaskState.PENDING},  # Can be reset and requeued
        TaskState.FAILED: {TaskState.PENDING},  # Can be reset and requeued
    }

    def __init__(
        self,
        current_state: str = TaskState.CREATED,
        max_retries: int = 3,
        retry_count: int = 0,
    ):
        self.state = TaskState(current_state)
        self.max_retries = max_retries
        self.retry_count = retry_count
        self.last_transition = datetime.now(timezone.utc)

    def validate_transition(self, new_state: TaskState) -> bool:
        """Validate if a state transition is allowed."""
        if new_state not in self.VALID_TRANSITIONS[self.state]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot transition from {self.state} to {new_state}",
            )
        return True

    def reset(self) -> TaskState:
        """Reset task settings and requeue.

        Transitions:
        - Any state -> PENDING (resets task settings and requeues)

        Resets:
        - retry_count back to 0
        - last_transition to now
        - state to PENDING for requeuing

        Note: This allows tasks to be requeued from any state,
        useful for retrying failed tasks or rerunning completed ones.
        """
        # Reset task settings
        self.retry_count = 0
        self.last_transition = datetime.now(timezone.utc)

        # Validate and perform transition to PENDING
        self.validate_transition(TaskState.PENDING)
        self.state = TaskState.PENDING

        return self.state

    def fetch(self) -> TaskState:
        """Fetch task for execution.

        Transitions:
        - PENDING -> RUNNING (task fetched for execution)
        - Others -> HTTPException (invalid)
        """
        if self.state == TaskState.PENDING:
            self.validate_transition(TaskState.RUNNING)
            self.state = TaskState.RUNNING
        else:
            raise HTTPException(
                status_code=400, detail=f"Cannot fetch task in {self.state} state"
            )
        return self.state

    def complete(self) -> TaskState:
        """Mark task as completed.

        Transitions:
        - RUNNING -> COMPLETED (successful completion)
        - Others -> HTTPException (invalid)

        Note: COMPLETED is a terminal state with no further transitions.
        """
        if self.state == TaskState.RUNNING:
            self.validate_transition(TaskState.COMPLETED)
            self.state = TaskState.COMPLETED
        else:
            raise HTTPException(
                status_code=400, detail=f"Cannot complete task in {self.state} state"
            )
        return self.state

    def fail(self, reason: Optional[str] = None) -> TaskState:
        """Mark task as failed with optional retry.

        Transitions:
        - RUNNING -> PENDING (if retry_count <= max_retries)
        - RUNNING -> FAILED (if retry_count > max_retries)
        - Others -> HTTPException (invalid)

        Args:
            reason: Optional reason for failure

        Note: FAILED state can transition back to PENDING for retries
        until max_retries is reached.
        """
        if self.state != TaskState.RUNNING:
            raise HTTPException(
                status_code=400, detail=f"Cannot fail task in {self.state} state"
            )

        self.retry_count += 1
        if self.retry_count <= self.max_retries:
            self.validate_transition(TaskState.PENDING)
            self.state = TaskState.PENDING
        else:
            self.validate_transition(TaskState.FAILED)
            self.state = TaskState.FAILED
        return self.state

    def to_dict(self) -> dict:
        """Convert FSM state to dictionary."""
        return {
            "state": self.state,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "last_transition": self.last_transition,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskFSM":
        """Create FSM from dictionary."""
        return cls(
            current_state=data.get("state", TaskState.CREATED),
            max_retries=data.get("max_retries", 3),
            retry_count=data.get("retry_count", 0),
        )
