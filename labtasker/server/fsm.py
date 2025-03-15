from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Set

from fastapi import HTTPException
from starlette.status import HTTP_500_INTERNAL_SERVER_ERROR

from labtasker.api_models import StateTransitionEvent
from labtasker.server.event_manager import event_manager
from labtasker.utils import get_current_time


class EntityType(str, Enum):
    TASK = "task"
    WORKER = "worker"


@dataclass
class StateTransitionEventHandle:
    """Handle for tracking state transition and event publishing"""

    entity_type: EntityType
    entity_id: str
    queue_id: str
    old_state: str
    new_state: str
    transition_time: datetime
    metadata: Dict[str, Any]
    _entity_data: Optional[Dict[str, Any]] = None

    def update_fsm_event(
        self, entity_data: Dict[str, Any], commit: bool = False
    ) -> None:
        """Update FSM event with entity data and trigger event publishing

        Args:
            entity_data:
            commit:
        """
        self._entity_data = entity_data
        if commit:
            self.commit()

    def commit(self):
        event_data = StateTransitionEvent(
            entity_type=self.entity_type,
            queue_id=self.queue_id,
            entity_id=self.entity_id,
            old_state=self.old_state,
            new_state=self.new_state,
            timestamp=self.transition_time,
            metadata=self.metadata,
            entity_data=self._entity_data,
        )

        # Use fully synchronous event publishing
        event_manager.publish_event(self.queue_id, event_data)
        self._entity_data = None


class State(str, Enum):
    def __str__(self):
        return self.value

    def __repr__(self):
        return self.value


class InvalidStateTransition(HTTPException):
    """Raised when attempting an invalid state transition."""

    def __init__(
        self,
        message: str,
        old_state: Optional[State] = None,
        new_state: Optional[State] = None,
    ):
        """

        Args:
            message:
            old_state: If None, consider not specified, as the transition event is invalid (e.g. task_fsm.fail() from PENDING)
            new_state: If None, consider not specified, as the transition event is invalid (e.g. task_fsm.fail() from PENDING)
        """
        super().__init__(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"InvalidStateTransition: {message}.",
        )
        self.message = message
        self.old_state = old_state
        self.new_state = new_state

    def __repr__(self):
        class_name = self.__class__.__name__
        return f"{class_name}(message={self.message}, old_state={self.old_state}, new_state={self.new_state})"


class TaskState(State):
    CREATED = "created"  # temporary state
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkerState(State):
    CREATED = "created"  # temporary state
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CRASHED = "crashed"


class BaseFSM:
    """Base class for state machine."""

    VALID_TRANSITIONS: Dict[Enum, Set[Enum]] = {}
    ENTITY_TYPE: EntityType  # To be set by subclasses

    def __init__(
        self,
        queue_id: str,
        entity_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """

        Args:
            queue_id:
            entity_id:
            metadata: metadata for the FSM event (optional), not necessarily metadata for the entity
        """
        self.queue_id = queue_id
        self.entity_id = entity_id
        self.metadata = metadata or {}
        self._state: Optional[State] = None

    @property
    def state(self):
        return self._state

    def transition_to(self, new_state: State) -> StateTransitionEventHandle:
        """Perform state transition and return a handle"""
        old_state = self._state
        self.validate_transition(new_state)
        self._state = new_state

        return StateTransitionEventHandle(
            entity_type=self.ENTITY_TYPE,
            entity_id=self.entity_id,
            queue_id=self.queue_id,
            old_state=str(old_state),
            new_state=str(new_state),
            transition_time=get_current_time(),
            metadata=self.metadata,
        )

    def validate_transition(self, new_state) -> bool:
        """Validate if a state transition is allowed."""
        if new_state not in self.VALID_TRANSITIONS[self.state]:
            raise InvalidStateTransition(
                f"Cannot transition from {self.state} to {new_state}",
                old_state=self.state,
                new_state=new_state,
            )
        return True

    def force_set_state(self, new_state: State) -> None:
        """Force set state without validation or event emission."""
        self._state = new_state


class TaskFSM(BaseFSM):
    ENTITY_TYPE = EntityType.TASK
    # Define valid state transitions
    VALID_TRANSITIONS = {
        TaskState.CREATED: {TaskState.PENDING},
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
        queue_id: str,
        entity_id: str,
        current_state: TaskState,
        retries: int,
        max_retries: int,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(queue_id=queue_id, entity_id=entity_id, metadata=metadata)
        self.force_set_state(current_state)
        self.retries = retries
        self.max_retries = max_retries

    @classmethod
    def from_db_entry(cls, db_entry: Mapping[str, Any]) -> "TaskFSM":
        """Instantiate FSM from database entry."""
        return cls(
            queue_id=db_entry["queue_id"],
            entity_id=db_entry["_id"],
            current_state=db_entry["status"],
            retries=db_entry["retries"],
            max_retries=db_entry["max_retries"],
            metadata=None,  # default event metadata to None
        )

    def create(self) -> StateTransitionEventHandle:
        """Create task."""
        if not self.state == TaskState.CREATED:
            raise InvalidStateTransition(
                f"Cannot create task from state {self.state}",
            )
        return self.transition_to(TaskState.PENDING)

    def cancel(self) -> StateTransitionEventHandle:
        """Cancel task.

        Transitions:
        - Any state -> CANCELLED (task is cancelled)
        """
        return self.transition_to(TaskState.CANCELLED)

    def reset(self) -> StateTransitionEventHandle:
        """Reset task settings and requeue.

        Transitions:
        - Any state -> PENDING (resets task settings and requeues)

        Resets:
        - retries back to 0
        - state to PENDING for requeuing

        Note: This allows tasks to be requeued from any state,
        useful for retrying failed tasks or rerunning success ones.
        """
        self.retries = 0
        return self.transition_to(TaskState.PENDING)

    def fetch(self) -> StateTransitionEventHandle:
        """Fetch task for execution.

        Transitions:
        - PENDING -> RUNNING (task fetched for execution)
        """
        return self.transition_to(TaskState.RUNNING)

    def complete(self) -> StateTransitionEventHandle:
        """Mark task as success.

        Transitions:
        - RUNNING -> SUCCESS (successful completion)
        - Others -> InvalidStateTransition (invalid)

        Note: SUCCESS is a terminal state with no further transitions.
        """
        return self.transition_to(TaskState.SUCCESS)

    def fail(self) -> StateTransitionEventHandle:
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
            return self.transition_to(TaskState.PENDING)
        else:
            return self.transition_to(TaskState.FAILED)


class WorkerFSM(BaseFSM):
    ENTITY_TYPE = EntityType.WORKER
    VALID_TRANSITIONS = {
        WorkerState.CREATED: {WorkerState.ACTIVE},
        WorkerState.ACTIVE: {
            WorkerState.ACTIVE,
            WorkerState.SUSPENDED,
            WorkerState.CRASHED,
        },
        WorkerState.SUSPENDED: {WorkerState.ACTIVE},  # Manual transition
        WorkerState.CRASHED: {WorkerState.ACTIVE},  # Manual transition
    }

    def __init__(
        self,
        queue_id: str,
        entity_id: str,
        current_state: WorkerState,
        retries: int,
        max_retries: int,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(queue_id=queue_id, entity_id=entity_id, metadata=metadata)
        self.force_set_state(current_state)
        self.retries = retries
        self.max_retries = max_retries

    @classmethod
    def from_db_entry(cls, db_entry: Mapping[str, Any]) -> "WorkerFSM":
        """Instantiate FSM from database entry."""
        return cls(
            queue_id=db_entry["queue_id"],
            entity_id=db_entry["_id"],
            current_state=db_entry["status"],
            retries=db_entry["retries"],
            max_retries=db_entry["max_retries"],
            metadata=None,  # default event metadata to None
        )

    def create(self) -> StateTransitionEventHandle:
        """Create worker."""
        if not self.state == WorkerState.CREATED:
            raise InvalidStateTransition(
                f"Cannot create worker from state {self.state}",
            )
        return self.transition_to(WorkerState.ACTIVE)

    def activate(self) -> StateTransitionEventHandle:
        """Activate worker. If previous state is crashed, reset retries to 0.

        Transitions:
        - Any state -> ACTIVE (worker resumes)
        """
        if self.state == WorkerState.CRASHED:
            self.retries = 0
        return self.transition_to(WorkerState.ACTIVE)

    def suspend(self) -> StateTransitionEventHandle:
        """Suspend worker.

        Transitions:
        - ACTIVE -> SUSPENDED (worker is suspended)
        """
        return self.transition_to(WorkerState.SUSPENDED)

    def fail(self) -> StateTransitionEventHandle:
        """Fail worker.

        Transitions:
        - ACTIVE -> ACTIVE
        - ACTIVE -> CRASHED (retries >= max_retries)
        """
        if self.state != WorkerState.ACTIVE:
            raise InvalidStateTransition(f"Cannot fail worker in {self.state} state")

        self.retries += 1
        if self.retries >= self.max_retries:
            return self.transition_to(WorkerState.CRASHED)
        return self.transition_to(WorkerState.ACTIVE)
