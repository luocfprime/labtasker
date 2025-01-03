from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set
from uuid import uuid4

from fastapi import HTTPException
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError, OperationFailure
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from .fsm import TaskFSM, TaskState
from .security import SecurityManager
from .utils import get_current_time, get_timeout_delta, parse_timeout

if TYPE_CHECKING:
    from .security import SecurityManager


class InvalidStateTransition(Exception):
    """Raised when attempting an invalid state transition."""

    pass


class WorkerStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CRASHED = "crashed"


class Priority(int, Enum):
    LOW = 0
    MEDIUM = 10  # default
    HIGH = 20


class WorkerFSM:
    """Worker state machine."""

    VALID_TRANSITIONS: Dict[WorkerStatus, Set[WorkerStatus]] = {
        WorkerStatus.ACTIVE: {WorkerStatus.SUSPENDED, WorkerStatus.CRASHED},
        WorkerStatus.SUSPENDED: {WorkerStatus.ACTIVE},
        WorkerStatus.CRASHED: {WorkerStatus.ACTIVE},
    }

    @classmethod
    def validate_transition(
        cls, current_state: WorkerStatus, new_state: WorkerStatus
    ) -> bool:
        """Validate if a state transition is allowed."""
        if new_state not in cls.VALID_TRANSITIONS[current_state]:
            raise InvalidStateTransition(
                f"Cannot transition from {current_state} to {new_state}"
            )
        return True


class DatabaseClient:
    def __init__(
        self, uri: str = None, db_name: str = None, client: Optional[MongoClient] = None
    ):
        """Initialize database client."""
        from .security import SecurityManager  # Import here to avoid circular import

        self.security = SecurityManager()
        if client:
            # Use provided client (for testing)
            self.client = client
            self.db = self.client[db_name]
            self._setup_collections()
            return

        if not uri or not db_name:
            raise ValueError("Either provide uri and db_name or a client instance")

        try:
            self.client = MongoClient(uri)
            if not isinstance(self.client, MongoClient):
                # Test connection only for real MongoDB (not mock)
                self.client.admin.command("ping")
            self.db: Database = self.client[db_name]
            self._setup_collections()
        except Exception as e:
            raise ConnectionError(f"Failed to connect to MongoDB: {str(e)}")

    def _setup_collections(self):
        """Setup collections and indexes."""
        # Queues collection
        self.queues: Collection = self.db.queues
        # _id is automatically indexed by MongoDB
        self.queues.create_index([("queue_name", ASCENDING)], unique=True)

        # Tasks collection
        self.tasks: Collection = self.db.tasks
        # _id is automatically indexed by MongoDB
        self.tasks.create_index([("queue_id", ASCENDING)])  # Reference to queue._id
        self.tasks.create_index([("status", ASCENDING)])
        self.tasks.create_index([("priority", ASCENDING)])

        # Workers collection
        self.workers: Collection = self.db.workers
        # _id is automatically indexed by MongoDB
        self.workers.create_index([("queue_id", ASCENDING)])  # Reference to queue._id
        self.workers.create_index(
            [("worker_name", ASCENDING)]
        )  # Optional index for searching

    def create_queue(self, queue_name: str, password: str) -> str:
        """Create a new queue."""
        try:
            # Validate queue name
            if not queue_name or not isinstance(queue_name, str):
                raise ValueError("Invalid queue name")

            queue = {
                "_id": str(uuid4()),
                "queue_name": queue_name,
                "password": self.security.hash_password(password),
                "created_at": get_current_time(),
            }
            result = self.queues.insert_one(queue)
            return str(result.inserted_id)
        except DuplicateKeyError:
            raise HTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=f"Queue '{queue_name}' already exists",
            )
        except ValueError as e:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to create queue: {str(e)}",
            )

    def submit_task(
        self,
        queue_name: str,
        task_name: Optional[str] = None,
        args: Dict[str, Any] = None,
        metadata: Dict[str, Any] = None,
        heartbeat_timeout: int = 60,
        task_timeout: Optional[
            int
        ] = None,  # Maximum time in seconds for task execution
        max_retries: int = 3,  # Maximum number of retries
    ) -> str:
        """Submit a task to a queue."""
        # Verify queue exists
        queue = self.queues.find_one({"queue_name": queue_name})
        if not queue:
            raise HTTPException(
                status_code=404, detail=f"Queue '{queue_name}' not found"
            )

        # Validate args
        if args is not None and not isinstance(args, dict):
            raise HTTPException(
                status_code=400, detail="Task args must be a dictionary"
            )

        now = get_current_time()

        fsm = TaskFSM(
            current_state=TaskState.CREATED, retry_count=0, max_retries=max_retries
        )
        task = {
            "_id": str(uuid4()),
            "queue_id": str(queue["_id"]),
            "queue_name": queue_name,
            "status": TaskState.CREATED,
            "retry_count": fsm.retry_count,
            "max_retries": fsm.max_retries,
            "task_name": task_name,
            "args": args or {},
            "metadata": metadata or {},
            "created_at": now,
            "last_modified": now,
            "heartbeat_timeout": heartbeat_timeout,
            "task_timeout": task_timeout,
            "last_heartbeat": None,
            "start_time": None,
        }
        result = self.tasks.insert_one(task)
        return str(result.inserted_id)

    def fetch_task(
        self,
        queue_name: str,
        worker_id: str,
        worker_name: Optional[str] = None,
        eta_max: str = "2h",
    ) -> Optional[Dict[str, Any]]:
        """Fetch next available task from queue."""
        timeout = parse_timeout(eta_max)

        # Get queue ID
        queue = self.queues.find_one({"queue_name": queue_name})
        if not queue:
            raise ValueError(f"Queue '{queue_name}' not found")

        now = get_current_time()
        # Find and update an available task
        result = self.tasks.find_one_and_update(
            {
                "queue_id": queue["_id"],
                "status": {"$in": [TaskState.CREATED, TaskState.PENDING]},
                "$or": [
                    {"worker_metadata": None},
                    {
                        "worker_metadata.status": WorkerStatus.CRASHED,
                        "retries": {"$lt": "$max_retries"},
                    },
                ],
            },
            {
                "$set": {
                    "status": TaskState.RUNNING,
                    "start_time": now,
                    "last_heartbeat": now,
                    "last_modified": now,
                    "worker_metadata": {
                        "worker_id": worker_id,
                        "worker_name": worker_name,
                        "queue_id": queue["_id"],
                        "status": WorkerStatus.ACTIVE,
                        "max_crash_count": 3,
                        "crash_count": 0,
                    },
                }
            },
            sort=[("priority", -1), ("created_at", 1)],
            return_document=True,
        )
        return result

    def update_task_status(
        self,
        task_id: str,
        status: TaskState,
        summary: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update task status."""
        try:
            # Get current task state
            task = self.tasks.find_one({"_id": task_id})
            if not task:
                raise ValueError(f"Task {task_id} not found")

            # Create FSM with current state
            fsm = TaskFSM(
                current_state=task["status"],
                retry_count=task.get("retry_count"),
                max_retries=task.get("max_retries"),
            )

            # Validate state transition
            fsm.validate_transition(status)

            result = self.tasks.update_one(
                {"_id": task_id},
                {
                    "$set": {
                        "status": status,
                        "retry_count": fsm.retry_count,
                        "last_modified": get_current_time(),
                        "summary": summary or {},
                    }
                },
            )
            return result.modified_count > 0
        except HTTPException as e:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=e.detail,
            )

    def handle_timeouts(self) -> List[str]:
        """Check and handle task timeouts."""
        now = get_current_time()
        transitioned_tasks = []

        # Build query
        query = {
            "status": TaskState.RUNNING,
            "$or": [
                # Heartbeat timeout
                {
                    "last_heartbeat": {"$ne": None},
                    "heartbeat_timeout": {"$ne": None},
                    "$expr": {
                        "$gt": [
                            {
                                "$divide": [
                                    {"$subtract": [now, "$last_heartbeat"]},
                                    1000,
                                ]
                            },
                            "$heartbeat_timeout",
                        ]
                    },
                },
                # Task execution timeout
                {
                    "task_timeout": {"$ne": None},
                    "start_time": {"$ne": None},
                    "$expr": {
                        "$gt": [
                            {"$divide": [{"$subtract": [now, "$start_time"]}, 1000]},
                            "$task_timeout",
                        ]
                    },
                },
            ],
        }

        # Find tasks that might have timed out
        tasks = self.tasks.find(query)

        tasks = list(tasks)  # Convert cursor to list

        for task in tasks:
            try:
                # Create FSM with current state
                fsm = TaskFSM(
                    current_state=task["status"],
                    retry_count=task.get("retry_count"),
                    max_retries=task.get("max_retries"),
                )

                # Transition to FAILED state through FSM
                fsm.fail(reason="Task timed out")

                # Update task in database
                result = self.tasks.update_one(
                    {"_id": task["_id"]},
                    {
                        "$set": {
                            "status": fsm.state,
                            "retry_count": fsm.retry_count,
                            "last_modified": get_current_time(),
                            "error": "Task timed out",
                            "worker_metadata": None,  # TODO: check. Clear worker metadata
                        }
                    },
                )
                if result.modified_count > 0:
                    transitioned_tasks.append(task["_id"])
            except Exception as e:
                # Log error but continue processing other tasks
                print(f"Error handling timeout for task {task['_id']}: {e}")

        return transitioned_tasks
