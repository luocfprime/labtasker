from enum import Enum
from typing import Dict, Set

from fastapi import HTTPException


class InvalidStateTransition(HTTPException):
    """Raised when attempting an invalid state transition."""

    def __init__(self, message: str):
        super().__init__(status_code=500, detail=message)


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkerState(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CRASHED = "crashed"


class FSMValidatorMixin:
    """Mixin class for state machine validation logic."""

    VALID_TRANSITIONS: Dict[Enum, Set[Enum]] = {}

    def __init__(self, current_state: Enum):
        self._state = current_state

    @property
    def state(self) -> Enum:
        return self._state

    @state.setter
    def state(self, new_state: Enum) -> None:
        self.validate_transition(new_state)
        self._state = new_state

    def validate_transition(self, new_state: Enum) -> bool:
        """Validate if a state transition is allowed."""
        if new_state not in self.VALID_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"Cannot transition from {self.state} to {new_state}",
            )
        return True

    def force_set_state(self, new_state: Enum) -> None:
        """Force set state without validation."""
        self._state = new_state


class TaskFSM(FSMValidatorMixin):
    # Define valid state transitions
    VALID_TRANSITIONS = {
        TaskState.PENDING: {TaskState.RUNNING, TaskState.PENDING},
        TaskState.RUNNING: {TaskState.COMPLETED, TaskState.FAILED, TaskState.PENDING},
        TaskState.COMPLETED: {TaskState.PENDING},  # Can be reset and requeued
        TaskState.FAILED: {TaskState.PENDING},  # Can be reset and requeued
    }

    def __init__(
        self,
        current_state: TaskState,
        retries: int,
        max_retries: int,
    ):
        super().__init__(current_state)
        self.retries = retries
        self.max_retries = max_retries

    def validate_transition(self, new_state: TaskState) -> bool:
        """Validate if a state transition is allowed."""
        if new_state not in self.VALID_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"Cannot transition from {self.state} to {new_state}",
            )
        return True

    def reset(self) -> TaskState:
        """Reset task settings and requeue.

        Transitions:
        - Any state -> PENDING (resets task settings and requeues)

        Resets:
        - retries back to 0
        - state to PENDING for requeuing

        Note: This allows tasks to be requeued from any state,
        useful for retrying failed tasks or rerunning completed ones.
        """
        # Reset task settings
        self.retries = 0

        self.state = TaskState.PENDING

        return self.state

    def fetch(self) -> TaskState:
        """Fetch task for execution.

        Transitions:
        - PENDING -> RUNNING (task fetched for execution)
        """
        self.state = TaskState.RUNNING
        return self.state

    def complete(self) -> TaskState:
        """Mark task as completed.

        Transitions:
        - RUNNING -> COMPLETED (successful completion)
        - Others -> InvalidStateTransition (invalid)

        Note: COMPLETED is a terminal state with no further transitions.
        """
        self.state = TaskState.COMPLETED
        return self.state

    def fail(self) -> TaskState:
        """Mark task as failed with optional retry.

        Transitions:
        - RUNNING -> PENDING (if retries < max_retries)
        - RUNNING -> FAILED (if retries >= max_retries)
        - Others -> InvalidStateTransition (invalid)

        Note: FAILED state can transition back to PENDING for retries
        until max_retries is reached.
        """
        if self.state != TaskState.RUNNING:
            raise InvalidStateTransition(f"Cannot fail task in {self.state} state")

        self.retries += 1
        if self.retries < self.max_retries:
            self.state = TaskState.PENDING
        else:
            self.state = TaskState.FAILED
        return self.state


class WorkerFSM(FSMValidatorMixin):
    VALID_TRANSITIONS = {
        WorkerState.ACTIVE: {
            WorkerState.ACTIVE,
            WorkerState.SUSPENDED,
            WorkerState.CRASHED,
        },
        WorkerState.SUSPENDED: {WorkerState.ACTIVE},  # Manual transition
        WorkerState.CRASHED: {WorkerState.ACTIVE},  # Manual transition
    }

    def __init__(self, current_state: WorkerState, retries: int, max_retries: int):
        super().__init__(current_state)
        self.retries = retries
        self.max_retries = max_retries

    def activate(self) -> WorkerState:
        """
        Activate worker.

        Transitions:
        - Any state -> ACTIVE (worker resumes)
        """
        self.state = WorkerState.ACTIVE
        return self.state

    def suspend(self) -> WorkerState:
        """
        Suspend worker.

        Transitions:
        - ACTIVE -> SUSPENDED (worker is suspended)
        """
        self.state = WorkerState.SUSPENDED
        return self.state

    def fail(self) -> WorkerState:
        """
        Fail worker.

        Transitions:
        - ACTIVE -> ACTIVE
        - ACTIVE -> CRASHED (retries >= max_retries)
        """
        if self.state != WorkerState.ACTIVE:
            raise InvalidStateTransition(f"Cannot fail worker in {self.state} state")

        self.retries += 1
        if self.retries >= self.max_retries:
            self.state = WorkerState.CRASHED
        return self.state
