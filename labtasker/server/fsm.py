from enum import Enum
from functools import wraps
from typing import Any, Dict, Mapping, Set

from fastapi import HTTPException
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR


def event(func):
    @wraps(func)
    def wrapper(fsm, *args, **kwargs):
        # TODO: dummy. Reserved for event-driven hooks. (low priority)
        return func(fsm, *args, **kwargs)

    return wrapper


class InvalidStateTransition(HTTPException):
    """Raised when attempting an invalid state transition."""

    def __init__(self, message: str):
        super().__init__(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"InvalidStateTransition: {message}",
        )


class State(str, Enum):
    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


class TaskState(State):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerState(State):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CRASHED = "crashed"


class FSMValidatorMixin:
    """Mixin class for state machine validation logic."""

    VALID_TRANSITIONS: Dict[Enum, Set[Enum]] = {}

    @property
    def state(self):
        return self._state

    @state.setter
    def state(self, new_state) -> None:
        self.validate_transition(new_state)
        self._state = new_state

    def validate_transition(self, new_state) -> bool:
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
        TaskState.PENDING: {TaskState.RUNNING, TaskState.PENDING, TaskState.CANCELLED},
        TaskState.RUNNING: {
            TaskState.SUCCESS,
            TaskState.FAILED,
            TaskState.PENDING,
            TaskState.CANCELLED,
        },
        TaskState.SUCCESS: {
            TaskState.PENDING,
            TaskState.CANCELLED,
        },  # Can be reset and requeued
        TaskState.FAILED: {
            TaskState.PENDING,
            TaskState.CANCELLED,
        },  # Can be reset and requeued
        TaskState.CANCELLED: {
            TaskState.PENDING,
            TaskState.CANCELLED,
        },  # Can be reset and requeued
    }

    def __init__(
        self,
        current_state: TaskState,
        retries: int,
        max_retries: int,
    ):
        self.force_set_state(current_state)
        self.retries = retries
        self.max_retries = max_retries

    @classmethod
    def from_db_entry(cls, db_entry: Mapping[str, Any]) -> "TaskFSM":
        """Instantiate FSM from database entry."""
        return cls(db_entry["status"], db_entry["retries"], db_entry["max_retries"])

    @event
    def cancel(self) -> TaskState:
        """Cancel task.

        Transitions:
        - Any state -> CANCELLED (task is cancelled)
        """
        self.state = TaskState.CANCELLED
        return self.state

    @event
    def reset(self) -> TaskState:
        """Reset task settings and requeue.

        Transitions:
        - Any state -> PENDING (resets task settings and requeues)

        Resets:
        - retries back to 0
        - state to PENDING for requeuing

        Note: This allows tasks to be requeued from any state,
        useful for retrying failed tasks or rerunning success ones.
        """
        # Reset task settings
        self.retries = 0

        self.state = TaskState.PENDING

        return self.state

    @event
    def fetch(self) -> TaskState:
        """Fetch task for execution.

        Transitions:
        - PENDING -> RUNNING (task fetched for execution)
        """
        self.state = TaskState.RUNNING
        return self.state

    @event
    def complete(self) -> TaskState:
        """Mark task as success.

        Transitions:
        - RUNNING -> SUCCESS (successful completion)
        - Others -> InvalidStateTransition (invalid)

        Note: SUCCESS is a terminal state with no further transitions.
        """
        self.state = TaskState.SUCCESS
        return self.state

    @event
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
        self.force_set_state(current_state)
        self.retries = retries
        self.max_retries = max_retries

    @classmethod
    def from_db_entry(cls, db_entry: Mapping[str, Any]) -> "WorkerFSM":
        """Instantiate FSM from database entry."""
        return cls(
            current_state=db_entry["status"],
            retries=db_entry["retries"],
            max_retries=db_entry["max_retries"],
        )

    @event
    def activate(self) -> WorkerState:
        """
        Activate worker. If previous state is crashed, reset retries to 0.

        Transitions:
        - Any state -> ACTIVE (worker resumes)
        """
        if self.state == WorkerState.CRASHED:
            self.retries = 0

        self.state = WorkerState.ACTIVE
        return self.state

    @event
    def suspend(self) -> WorkerState:
        """
        Suspend worker.

        Transitions:
        - ACTIVE -> SUSPENDED (worker is suspended)
        """
        self.state = WorkerState.SUSPENDED
        return self.state

    @event
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
