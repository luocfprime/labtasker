import contextlib
import contextvars
from typing import Any, Dict, List, Mapping, Optional, Union
from uuid import uuid4

from fastapi import HTTPException
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection, ReturnDocument
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError
from starlette.status import (
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from labtasker.constants import Priority
from labtasker.security import hash_password
from labtasker.server.db_utils import (
    merge_filter,
    query_dict_to_mongo_filter,
    sanitize_query,
    validate_arg,
)
from labtasker.server.fsm import TaskFSM, TaskState, WorkerFSM, WorkerState
from labtasker.utils import (
    arg_match,
    auth_required,
    flatten_dict,
    get_current_time,
    parse_timeout,
    risky,
    sanitize_dict,
    sanitize_update,
)

_in_transaction = contextvars.ContextVar("in_transaction", default=False)


class DBService:
    def __init__(
        self, db_name: str, uri: str = None, client: Optional[MongoClient] = None
    ):
        """Initialize database client. If client is provided, it will be used instead of connecting to MongoDB."""
        if client:
            self._client = client
            self._db = self._client[db_name]
            self._setup_collections()
            return

        try:
            self._client = MongoClient(uri, w="majority", retryWrites=True)
            self._client.admin.command("ping")
            self._db: Database = self._client[db_name]
            self._setup_collections()
        except Exception as e:
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to connect to MongoDB: {str(e)}",
            )

    @contextlib.contextmanager
    def transaction(self, allow_nesting: bool = False):
        """Context manager for database transactions.

        Args:
            allow_nesting (bool): Whether to detect and ban nested transactions
        """
        # Check if already in transaction
        if _in_transaction.get() and not allow_nesting:
            # raise error
            raise HTTPException(
                status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Nested transactions are not allowed",
            )

        # Set transaction flag and get token for resetting
        token = _in_transaction.set(True)
        try:
            with self._client.start_session() as session:
                with session.start_transaction():
                    try:
                        yield session
                        session.commit_transaction()
                    except Exception as e:
                        session.abort_transaction()
                        if isinstance(e, HTTPException):
                            raise e
                        raise HTTPException(
                            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"Transaction failed: {str(e)}",
                        )
        finally:
            # Reset transaction flag using token
            _in_transaction.reset(token)

    def ping(self):
        self._client.admin.command("ping")

    def is_empty(self):
        return (
            self._queues.count_documents({}) == 0
            and self._tasks.count_documents({}) == 0
            and self._workers.count_documents({}) == 0
        )

    def _setup_collections(self):
        """Setup collections and indexes."""
        # Queues collection
        self._queues: Collection = self._db.queues
        # _id is automatically indexed by MongoDB
        self._queues.create_index([("queue_name", ASCENDING)], unique=True)

        # Tasks collection
        self._tasks: Collection = self._db.tasks
        # _id is automatically indexed by MongoDB
        self._tasks.create_index([("queue_id", ASCENDING)])  # Reference to queue._id
        self._tasks.create_index([("status", ASCENDING)])
        self._tasks.create_index([("priority", DESCENDING)])  # Higher priority first
        self._tasks.create_index([("created_at", ASCENDING)])  # Older tasks first

        # Workers collection
        self._workers: Collection = self._db.workers
        # _id is automatically indexed by MongoDB
        self._workers.create_index([("queue_id", ASCENDING)])  # Reference to queue._id
        self._workers.create_index(
            [("worker_name", ASCENDING)]
        )  # Optional index for searching

    def close(self):
        """Close the database client."""
        self._client.close()

    def erase(self):
        """Erase all data"""
        self._queues.delete_many({})
        self._tasks.delete_many({})
        self._workers.delete_many({})

    @property
    def projection(self):
        return {"password": 0}

    @auth_required
    @risky("Potential query injection")
    @validate_arg
    def query_collection(
        self,
        queue_id: str,
        collection_name: str,
        query: Dict[str, Any],  # MongoDB query
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query a collection."""
        with self.transaction() as session:
            if collection_name not in ["queues", "tasks", "workers"]:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail="Invalid collection name. Must be one of: queues, tasks, workers",
                )

            # Prevent query injection
            query = sanitize_query(queue_id, query)

            result = (
                self._db[collection_name]
                .find(query, self.projection, session=session)
                .limit(limit)
            )

            return list(result)

    @auth_required
    @risky("Potential query injection")
    @validate_arg
    def update_collection(
        self,
        queue_id: str,
        collection_name: str,
        query: Dict[str, Any],  # MongoDB query
        update: Dict[str, Any],  # MongoDB update
    ) -> bool:
        """Update a collection."""
        with self.transaction() as session:
            if collection_name not in ["queues", "tasks", "workers"]:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail="Invalid collection name. Must be one of: queues, tasks, workers",
                )

            # Prevent query injection
            query = sanitize_query(queue_id, query)

            now = get_current_time()

            update = sanitize_update(
                update
            )  # make sure important fields are not tempered with

            if update.get("$set"):
                update["$set"]["last_modified"] = now
            else:
                update["$set"] = {"last_modified": now}

            result = self._db[collection_name].update_many(
                query, update, session=session
            )
            return result.modified_count > 0

    @validate_arg
    def create_queue(
        self,
        queue_name: str,
        password: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create a new queue."""
        if not queue_name:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST, detail="Queue name is required"
            )
        with self.transaction() as session:
            try:
                now = get_current_time()
                queue = {
                    "_id": str(uuid4()),
                    "queue_name": queue_name,
                    "password": hash_password(password),
                    "created_at": now,
                    "last_modified": now,
                    "metadata": metadata or {},
                }
                result = self._queues.insert_one(queue, session=session)
                return str(result.inserted_id)
            except DuplicateKeyError:
                raise HTTPException(
                    status_code=HTTP_409_CONFLICT,
                    detail=f"Queue '{queue_name}' already exists",
                )

    @auth_required
    @validate_arg
    def create_task(
        self,
        queue_id: str,
        task_name: Optional[str] = None,
        args: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        cmd: Optional[Union[str, List[str]]] = None,
        heartbeat_timeout: int = 60,
        task_timeout: Optional[
            int
        ] = None,  # Maximum time in seconds for task execution
        max_retries: int = 3,  # Maximum number of retries
        priority: int = Priority.MEDIUM,
    ) -> str:
        """Create a task related to a queue."""
        with self.transaction() as session:
            now = get_current_time()

            # fsm = TaskFSM(
            #     current_state=TaskState.PENDING, retries=0, max_retries=max_retries
            # )
            # fsm.reset()

            task = {
                "_id": str(uuid4()),
                "queue_id": str(queue_id),
                "status": TaskState.PENDING,
                "task_name": task_name,
                "created_at": now,
                "start_time": None,
                "last_heartbeat": None,
                "last_modified": now,
                "heartbeat_timeout": heartbeat_timeout,
                "task_timeout": task_timeout,
                "max_retries": max_retries,
                "retries": 0,
                "priority": priority,
                "metadata": metadata or {},
                "args": args or {},
                "cmd": cmd or "",
                "summary": {},
                "worker_id": None,
            }
            result = self._tasks.insert_one(task, session=session)
            return str(result.inserted_id)

    @auth_required
    @validate_arg
    def create_worker(
        self,
        queue_id: str,
        worker_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> str:
        """Create a worker."""
        with self.transaction() as session:
            now = get_current_time()

            worker = {
                "_id": str(uuid4()),
                "queue_id": queue_id,
                "status": WorkerState.ACTIVE,
                "worker_name": worker_name,
                "metadata": metadata or {},
                "retries": 0,
                "max_retries": max_retries,
                "created_at": now,
                "last_modified": now,
            }
            result = self._workers.insert_one(worker, session=session)
            return str(result.inserted_id)

    @auth_required
    @validate_arg
    def delete_queue(
        self,
        queue_id,
        cascade_delete: bool = False,  # TODO: need consideration
    ) -> bool:
        """
        Delete a queue.

        Args:
            queue_id (str): The id of the queue to delete.
            cascade_delete (bool): Whether to delete all tasks and workers in the queue.
        """
        with self.transaction() as session:
            # Delete queue
            self._queues.delete_one({"_id": queue_id}, session=session)

            if cascade_delete:
                # Delete all tasks in the queue
                self._tasks.delete_many({"queue_id": queue_id}, session=session)
                # Delete all workers in the queue
                self._workers.delete_many({"queue_id": queue_id}, session=session)

            return True

    @auth_required
    @validate_arg
    def delete_task(
        self,
        queue_id: str,
        task_id: str,
    ) -> bool:
        """Delete a task."""
        with self.transaction() as session:
            # Delete task
            result = self._tasks.delete_one(
                {"_id": task_id, "queue_id": queue_id}, session=session
            )
            if result.deleted_count == 0:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND, detail="Task not found"
                )
            return result.deleted_count > 0

    @auth_required
    @validate_arg
    def delete_worker(
        self,
        queue_id: str,
        worker_id: str,
        cascade_update: bool = True,
    ) -> bool:
        """
        Delete a worker.

        Args:
            queue_id (str): The name of the queue to delete the worker from.
            worker_id (str): The ID of the worker to delete.
            cascade_update (bool): Whether to set worker_id to None for associated tasks.
        """
        with self.transaction() as session:
            # Delete worker
            worker_result = self._workers.delete_one(
                {"_id": worker_id, "queue_id": queue_id}, session=session
            )
            if worker_result.deleted_count == 0:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND, detail="Worker not found"
                )

            now = get_current_time()
            if cascade_update:
                # Update all tasks associated with the worker
                self._tasks.update_many(
                    {"queue_id": queue_id, "worker_id": worker_id},
                    {"$set": {"worker_id": None, "last_modified": now}},
                    session=session,
                )

            return True

    @auth_required
    @validate_arg
    def update_queue(
        self,
        queue_id: str,
        new_queue_name: Optional[str] = None,
        new_password: Optional[str] = None,
        metadata_update: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update queue settings."""
        with self.transaction() as session:
            # Make sure name does not already exist
            if new_queue_name and self._get_queue_by_name(
                new_queue_name, session=session
            ):
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail=f"Queue name '{new_queue_name}' already exists",
                )

            update_dict = {}

            if new_queue_name:
                update_dict["queue_name"] = new_queue_name
            if new_password:
                update_dict["password"] = hash_password(new_password)

            if metadata_update:
                metadata_update = sanitize_dict(metadata_update)
                metadata_update = flatten_dict(metadata_update, parent_key="metadata")
            else:
                metadata_update = {}

            # Update queue settings
            update = {
                "$set": {
                    "last_modified": get_current_time(),
                    **update_dict,
                    **metadata_update,
                }
            }
            result = self._queues.update_one({"_id": queue_id}, update, session=session)
            return result.modified_count > 0

    # @risky("Potential query injection")
    @auth_required
    @validate_arg
    def fetch_task(
        self,
        queue_id: str,
        worker_id: Optional[str] = None,
        eta_max: Optional[str] = None,
        start_heartbeat: bool = True,
        required_fields: Optional[Dict[str, Any]] = None,
        extra_filter: Optional[Dict[str, Any]] = None,
    ) -> Optional[Mapping[str, Any]]:
        """
        Fetch next available task from queue.
        1. Fetch task from queue
        2. Set task status to RUNNING
        3. Set task worker_id to worker_id (if provided)
        4. Update related timestamps
        5. Return task

        Args:
            queue_id (str): The id of the queue to fetch the task from.
            worker_id (str, optional): The ID of the worker to assign the task to.
            eta_max (str, optional): The maximum time to wait for the task to be available.
            extra_filter (Dict[str, Any], optional): Additional filter criteria for the task.
        """
        task_timeout = parse_timeout(eta_max) if eta_max else None

        with self.transaction() as session:
            # Verify worker status if specified
            if worker_id:
                worker = self._workers.find_one(
                    {"_id": worker_id, "queue_id": queue_id}, session=session
                )
                if not worker:
                    raise HTTPException(
                        status_code=HTTP_404_NOT_FOUND,
                        detail=f"Worker '{worker_id}' not found in queue '{queue_id}'",
                    )
                worker_status = worker["status"]
                if worker_status != WorkerState.ACTIVE:
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"Worker '{worker_id}' is {worker_status} in queue '{queue_id}'",
                    )

            # Fetch task
            now = get_current_time()

            required_fields_filter = (
                query_dict_to_mongo_filter(required_fields, parent_key="args")
                if required_fields
                else None
            )

            combined_filter = merge_filter(
                required_fields_filter, extra_filter, logical_op="and"
            )

            sanitized_filter = sanitize_query(queue_id, combined_filter)

            # Construct the query
            query = {
                "queue_id": queue_id,
                "status": TaskState.PENDING,
                **sanitized_filter,
            }

            update = {
                "$set": {
                    "status": TaskState.RUNNING,
                    "start_time": now,
                    "last_heartbeat": now if start_heartbeat else None,
                    "last_modified": now,
                    "worker_id": worker_id,
                }
            }

            if task_timeout:
                update["$set"]["task_timeout"] = task_timeout

            tasks = self._tasks.find(
                query, session=session, sort=[("priority", -1), ("created_at", 1)]
            )

            for task in tasks:
                if task:
                    if required_fields and not arg_match(required_fields, task["args"]):
                        continue  # Skip to the next task if it doesn't match

                    updated_task = self._tasks.find_one_and_update(
                        {"_id": task["_id"]},
                        update,
                        session=session,
                        return_document=ReturnDocument.AFTER,
                    )

                    if updated_task:
                        return updated_task

            return None  # Return None if no tasks matched

    @auth_required
    @validate_arg
    def update_task_heartbeat(
        self,
        queue_id: str,
        task_id: str,
    ) -> bool:
        """Update task heartbeat timestamp."""
        with self.transaction() as session:
            return (
                self._tasks.update_one(
                    {"_id": task_id, "queue_id": queue_id},
                    {"$set": {"last_heartbeat": get_current_time()}},
                    session=session,
                ).modified_count
                > 0
            )

    @auth_required
    @validate_arg
    def update_task_status(
        self,
        queue_id: str,
        task_id: str,
        report_status: str,
        summary_update: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update task status. Used for reporting task execution results.
        """
        with self.transaction() as session:
            task = self._tasks.find_one(
                {"_id": task_id, "queue_id": queue_id}, session=session
            )
            if not task:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found"
                )

            try:
                fsm = TaskFSM.from_db_entry(task)

                if report_status == "success":
                    fsm.complete()
                elif report_status == "failed":
                    fsm.fail()
                elif report_status == "cancelled":
                    fsm.cancel()
                else:
                    raise HTTPException(
                        status_code=HTTP_400_BAD_REQUEST,
                        detail=f"Invalid report_status: {report_status}",
                    )

            except Exception as e:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail=str(e),
                )

            if summary_update:
                summary_update = sanitize_dict(summary_update)
                summary_update = flatten_dict(summary_update, parent_key="summary")
            else:
                summary_update = {}

            update = {
                "$set": {
                    "status": fsm.state,
                    "retries": fsm.retries,
                    "last_modified": get_current_time(),
                    **summary_update,
                }
            }

            result = self._tasks.update_one({"_id": task_id}, update, session=session)

            # Update worker status if worker is specified
            if report_status == "failed" and task["worker_id"]:
                worker_updated = self._update_worker_status(
                    queue_id=queue_id,
                    worker_id=task["worker_id"],
                    report_status="failed",
                    session=session,
                )
                return worker_updated and result.modified_count > 0

            return result.modified_count > 0

    @auth_required
    @validate_arg
    def update_task_and_reset_pending(
        self,
        queue_id: str,
        task_id: str,
        task_setting_update: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update task settings (optional) and set task status to PENDING.
        Can be used to manually restart crashed tasks after max retries.

        Args:
            queue_id (str): The name of the queue to update the task in.
            task_id (str): The ID of the task to update.
            task_setting_update (Dict[str, Any], optional): A dictionary of task settings to update.
        """
        with self.transaction() as session:
            # Update task settings
            if task_setting_update:
                task_setting_update = sanitize_update(task_setting_update)
                task_setting_update = flatten_dict(task_setting_update)
            else:
                task_setting_update = {}

            task_setting_update["last_modified"] = get_current_time()
            task_setting_update["status"] = TaskState.PENDING
            task_setting_update["retries"] = 0

            update = {
                "$set": {
                    **task_setting_update,
                }
            }

            result = self._tasks.update_one(
                {"_id": task_id, "queue_id": queue_id}, update, session=session
            )
            return result.modified_count > 0

    @auth_required
    @validate_arg
    def cancel_task(
        self,
        queue_id: str,
        task_id: str,
    ) -> bool:
        """Cancel a task."""
        with self.transaction() as session:
            # Cancel task
            result = self._tasks.update_one(
                {"_id": task_id, "queue_id": queue_id},
                {
                    "$set": {
                        "status": TaskState.CANCELLED,
                        "last_modified": get_current_time(),
                    }
                },
                session=session,
            )
            return result.modified_count > 0

    def _update_worker_status(
        self, queue_id: str, worker_id: str, report_status: str, session=None
    ) -> bool:
        """Internal method to update worker status."""
        worker = self._workers.find_one(
            {"_id": worker_id, "queue_id": queue_id}, session=session
        )
        if not worker:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail=f"Worker {worker_id} not found"
            )

        try:
            fsm = WorkerFSM.from_db_entry(worker)

            if report_status == "active":
                fsm.activate()
            elif report_status == "suspended":
                fsm.suspend()
            elif report_status == "failed":
                fsm.fail()
            else:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail=f"Invalid report_status: {report_status}",
                )

        except Exception as e:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        update = {
            "$set": {
                "status": fsm.state,
                "retries": fsm.retries,
                "last_modified": get_current_time(),
            }
        }

        result = self._workers.update_one({"_id": worker_id}, update, session=session)
        return result.modified_count > 0

    @auth_required
    @validate_arg
    def update_worker_status(
        self,
        queue_id: str,
        worker_id: str,
        report_status: str,
    ) -> bool:
        """Update worker status."""
        with self.transaction() as session:
            # Verify queue exists
            return self._update_worker_status(
                queue_id=queue_id,
                worker_id=worker_id,
                report_status=report_status,
                session=session,
            )

    def _get_queue_by_name(self, queue_name: str, session=None) -> Mapping[str, Any]:
        """Get queue by name with error handling.

        Args:
            queue_name: Name of queue to find
            session: Optional MongoDB session for transactions

        Returns:
            Queue document

        Raises:
            HTTPException: If queue not found
        """
        queue = self._queues.find_one({"queue_name": queue_name}, session=session)
        if not queue:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND, detail=f"Queue '{queue_name}' not found"
            )
        return queue

    @validate_arg
    def get_queue(
        self,
        queue_id: Optional[str] = None,
        queue_name: Optional[str] = None,
    ) -> Mapping[str, Any]:
        """Get queue by id or name. Name and id must match."""
        with self.transaction() as session:
            if queue_id:
                queue = self._queues.find_one({"_id": queue_id}, session=session)
            else:
                queue = self._get_queue_by_name(queue_name, session=session)

            if not queue:
                raise HTTPException(
                    status_code=HTTP_404_NOT_FOUND,
                    detail=f"Queue '{queue_name}' not found",
                )

            # Make sure the provided queue_name and queue_id match
            if queue_id and queue["_id"] != queue_id:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail=f"Queue '{queue_name}' does not match queue_id '{queue_id}'",
                )

            if queue_name and queue["queue_name"] != queue_name:
                raise HTTPException(
                    status_code=HTTP_400_BAD_REQUEST,
                    detail=f"Queue '{queue_name}' does not match queue_id '{queue_id}'",
                )

            return queue

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

        with self.transaction() as session:
            # Find tasks that might have timed out
            tasks = self._tasks.find(query, session=session)

            tasks = list(tasks)  # Convert cursor to list

            for task in tasks:
                try:
                    # Create FSM with current state
                    fsm = TaskFSM(
                        current_state=task["status"],
                        retries=task.get("retries"),
                        max_retries=task.get("max_retries"),
                    )

                    # Transition to FAILED state through FSM
                    fsm.fail()

                    # Update worker status if worker is specified
                    if task["worker_id"]:
                        self._update_worker_status(
                            queue_id=task["queue_id"],
                            worker_id=task["worker_id"],
                            report_status="failed",
                            session=session,
                        )

                    # Update task in database
                    result = self._tasks.update_one(
                        {"_id": task["_id"]},
                        {
                            "$set": {
                                "status": fsm.state,
                                "retries": fsm.retries,
                                "last_modified": now,
                                "summary.labtasker_error": "Either heartbeat or task execution timed out",
                            }
                        },
                        session=session,
                    )
                    if result.modified_count > 0:
                        transitioned_tasks.append(task["_id"])
                except Exception as e:
                    # Log error but continue processing other tasks
                    print(
                        f"Error handling timeout for task {task['_id']}: {e}"
                    )  # TODO: log

            return transitioned_tasks
