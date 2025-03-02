import asyncio
from asyncio import create_task
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, HTTPException
from starlette.status import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from labtasker.api_models import (
    QueueCreateRequest,
    QueueCreateResponse,
    QueueGetResponse,
    QueueUpdateRequest,
    Task,
    TaskFetchRequest,
    TaskFetchResponse,
    TaskLsRequest,
    TaskLsResponse,
    TaskStatusUpdateRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
    TaskUpdateRequest,
    Worker,
    WorkerCreateRequest,
    WorkerCreateResponse,
    WorkerLsRequest,
    WorkerLsResponse,
    WorkerStatusUpdateRequest,
)
from labtasker.server.config import get_server_config
from labtasker.server.database import DBService
from labtasker.server.dependencies import get_db, get_verified_queue_dependency
from labtasker.server.logging import logger
from labtasker.utils import get_current_time, parse_obj_as, unflatten_dict


async def periodic_task(app: FastAPI, interval_seconds: float):
    """Run a periodic task at specified intervals."""
    while True:
        try:
            # logger.info(
            #     f"now: {get_current_time()}, current_event_loop: {asyncio.get_running_loop().__hash__()}"
            # )
            db = get_db()
            transitioned_tasks = db.handle_timeouts()
            app.state.prev_polling = get_current_time().timestamp()
            if transitioned_tasks:
                logger.info(f"Transitioned {len(transitioned_tasks)} timed out tasks")
        except Exception as e:
            logger.info(f"Error checking timeouts: {e}")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan and background tasks."""
    # Setup
    config = get_server_config()
    task = create_task(periodic_task(app, config.periodic_task_interval))

    app.state.prev_polling = get_current_time().timestamp()

    yield

    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health_check():
    """Basic health check."""
    return {"connection": "ok"}


@app.get("/health/full")
def full_health_check(db: DBService = Depends(get_db)):
    """Full health check with database."""
    try:
        db.ping()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.get("/api/v1/polling")
def get_polling():
    """Get the previous polling time"""
    return {
        "prev_polling": app.state.prev_polling,
        "next_eta": (
            app.state.prev_polling
            + get_server_config().periodic_task_interval
            - get_current_time().timestamp()
        ),
        "polling_interval": get_server_config().periodic_task_interval,
    }


@app.post("/api/v1/queues", status_code=HTTP_201_CREATED)
def create_queue(queue: QueueCreateRequest, db: DBService = Depends(get_db)):
    """Create a new queue"""
    queue_id = db.create_queue(
        queue_name=queue.queue_name,
        password=queue.password.get_secret_value(),
        metadata=queue.metadata,
    )
    return QueueCreateResponse(queue_id=queue_id)


@app.get(
    "/api/v1/queues/me", response_model=QueueGetResponse, response_model_by_alias=False
)
def get_queue(queue: Dict[str, Any] = Depends(get_verified_queue_dependency)):
    """Get queue information"""
    return parse_obj_as(QueueGetResponse, queue)


@app.put(
    "/api/v1/queues/me", response_model=QueueGetResponse, response_model_by_alias=False
)
def update_queue(
    update_request: QueueUpdateRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Update queue details."""
    db.update_queue(
        queue_id=queue["_id"],
        new_queue_name=update_request.new_queue_name,
        new_password=(
            update_request.new_password.get_secret_value()
            if update_request.new_password
            else None
        ),
        metadata_update=update_request.metadata_update,
    )
    updated_queue = db.get_queue(queue_id=queue["_id"])
    return parse_obj_as(QueueGetResponse, updated_queue)


@app.delete("/api/v1/queues/me", status_code=HTTP_204_NO_CONTENT)
def delete_queue(
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    cascade_delete: bool = False,
    db: DBService = Depends(get_db),
):
    """Delete a queue"""
    if db.delete_queue(queue_id=queue["_id"], cascade_delete=cascade_delete) == 0:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Queue not found",
        )


@app.post("/api/v1/queues/me/tasks", status_code=HTTP_201_CREATED)
def submit_task(
    task: TaskSubmitRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Submit a task to the queue"""
    task_id = db.create_task(
        queue_id=queue["_id"],
        task_name=task.task_name,
        args=task.args,
        metadata=task.metadata,
        cmd=task.cmd,
        heartbeat_timeout=task.heartbeat_timeout,
        task_timeout=task.task_timeout,
        max_retries=task.max_retries,
        priority=task.priority,
    )
    return TaskSubmitResponse(task_id=task_id)


@app.post(
    "/api/v1/queues/me/tasks/search",
    response_model=TaskLsResponse,
    response_model_by_alias=False,
)
def ls_tasks(
    task_request: TaskLsRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Get tasks matching the criteria"""
    # Build task query
    task_query = task_request.extra_filter or {}
    task_query["queue_id"] = queue["_id"]

    if task_request.task_id:
        task_query["_id"] = task_request.task_id
    if task_request.task_name:
        task_query["task_name"] = task_request.task_name

    tasks = db.query_collection(
        queue_id=queue["_id"],
        collection_name="tasks",
        query=task_query,
        limit=task_request.limit,
        offset=task_request.offset,
    )
    if not tasks:
        return TaskLsResponse(found=False)

    return TaskLsResponse(found=True, content=parse_obj_as(List[Task], tasks))


@app.post(
    "/api/v1/queues/me/tasks/next",
    response_model=TaskFetchResponse,
    response_model_by_alias=False,
)
def fetch_task(
    task_request: TaskFetchRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """
    Get next available task from queue.
    Note: this is not an idempotent operation since the internal state changes according to FSM.
    """
    task = db.fetch_task(
        queue_id=queue["_id"],
        worker_id=task_request.worker_id,
        eta_max=task_request.eta_max,
        heartbeat_timeout=task_request.heartbeat_timeout,
        start_heartbeat=task_request.start_heartbeat,
        required_fields=task_request.required_fields,
        extra_filter=task_request.extra_filter,
    )

    if not task:
        return TaskFetchResponse(found=False)
    return TaskFetchResponse(found=True, task=parse_obj_as(Task, task))


@app.post("/api/v1/queues/me/tasks/{task_id}/status")
def report_task_status(
    task_id: str,
    update: TaskStatusUpdateRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Report task status (success, failed, cancelled)
    The if-else is to prevent the following conflicting scenario:
       1. task foo assigned to worker A.
       2. worker A timed out while running.
       3. task foo reassigned to worker B.
       4. worker A report task status, but the task is actually run by worker B, which leads to confusion.
    """
    if update.worker_id is not None:
        done = db.worker_report_task_status(
            queue_id=queue["_id"],
            task_id=task_id,
            worker_id=update.worker_id,
            report_status=update.status,
            summary_update=update.summary,
        )
    else:
        done = db.report_task_status(
            queue_id=queue["_id"],
            task_id=task_id,
            report_status=update.status,
            summary_update=update.summary,
        )
    if not done:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR)


@app.post(
    "/api/v1/queues/me/tasks/{task_id}/heartbeat", status_code=HTTP_204_NO_CONTENT
)
def refresh_task_heartbeat(
    task_id: str,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Update task heartbeat timestamp."""
    done = db.refresh_task_heartbeat(
        queue_id=queue["_id"],
        task_id=task_id,
    )
    if not done:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Task not found.")


@app.get(
    "/api/v1/queues/me/tasks/{task_id}",
    response_model=Task,
    response_model_by_alias=False,
)
def get_task(
    task_id: str,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Get a specific task by ID."""
    task = db.get_task(queue_id=queue["_id"], task_id=task_id)
    if not task:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Task not found")
    return parse_obj_as(Task, task)


@app.put(
    "/api/v1/queues/me/tasks",
    response_model=TaskLsResponse,
    response_model_by_alias=False,
)
def update_tasks(
    task_updates: List[TaskUpdateRequest],
    reset_pending: bool = True,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    if len(task_updates) == 0:
        return TaskLsResponse(found=False)
    elif len(task_updates) > 1000:
        raise HTTPException(
            status_code=HTTP_400_BAD_REQUEST,
            detail="Too many tasks to update. Maximum is 1000.",
        )

    for task_update in task_updates:
        update = {}
        replace_fields = task_update.replace_fields
        # to convert it into a dict of {"field_a.sub_field_a": "value"}}
        # e.g. {"args": {"arg1": 0}, "metadata": {"label": "test"}} ->
        # {"args.arg1": 0, "metadata.label": "test"}
        # we need to flatten by 1-level and add prefix
        for key, value in task_update.model_dump(
            exclude_unset=True, by_alias=True
        ).items():
            if key == "replace_fields":
                continue
            if key in replace_fields:  # replace root field
                if isinstance(value, dict):
                    # prevent {"args": {"foo.bar": 0}} case. (this can cause trouble for updating,
                    # because if {"foo.bar": 0} is assigned to args (i.e. ["args"]["foo.bar"]),
                    # updating args.foo.bar later would actually update the value of ["args"]["foo"]["bar"]
                    # rather than the existing db entry ["args"]["foo.bar"]
                    # therefore, only format like {"args": {"foo":{"bar": 0}}} should be allowed.
                    update[key] = unflatten_dict(value)
                else:
                    update[key] = value
            else:
                if isinstance(value, dict):  # only update sub-fields
                    # in this case, {"args": {"foo.bar": 0}} is allowed
                    # since it will be transformed to {"args.foo.bar": 0} for updating
                    for sub_key, sub_value in value.items():
                        update[f"{key}.{sub_key}"] = sub_value
                else:  # for non-dict, just overwrite the field
                    update[key] = value

        if not db.update_task(
            queue_id=queue["_id"],
            task_id=task_update.task_id,
            task_setting_update=update,
            reset_pending=reset_pending,
        ):
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=f"Task {task_update.task_id} not found.",
            )

    tasks = []
    for task in task_updates:
        tasks.append(db.get_task(queue_id=queue["_id"], task_id=task.task_id))

    return TaskLsResponse(found=True, content=parse_obj_as(List[Task], tasks))


@app.delete("/api/v1/queues/me/tasks/{task_id}", status_code=HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Delete a specific task."""
    deleted_count = db.delete_task(queue_id=queue["_id"], task_id=task_id)
    if deleted_count == 0:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Task not found",
        )


@app.post("/api/v1/queues/me/workers", status_code=HTTP_201_CREATED)
def create_worker(
    worker: WorkerCreateRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Create a new worker."""
    worker_id = db.create_worker(
        queue_id=queue["_id"],
        worker_name=worker.worker_name,
        metadata=worker.metadata,
        max_retries=worker.max_retries,
    )
    return WorkerCreateResponse(worker_id=worker_id)


@app.post(
    "/api/v1/queues/me/workers/search",
    response_model=WorkerLsResponse,
    response_model_by_alias=False,
)
def ls_worker(
    worker_request: WorkerLsRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Get worker information."""
    worker_query = worker_request.extra_filter or {}
    worker_query["queue_id"] = queue["_id"]

    if worker_request.worker_id:
        worker_query["_id"] = worker_request.worker_id
    if worker_request.worker_name:
        worker_query["worker_name"] = worker_request.worker_name

    workers = db.query_collection(
        queue_id=queue["_id"],
        collection_name="workers",
        query=worker_query,
        limit=worker_request.limit,
        offset=worker_request.offset,
    )
    if not workers:
        return WorkerLsResponse(found=False)

    return WorkerLsResponse(found=True, content=parse_obj_as(List[Worker], workers))


@app.post("/api/v1/queues/me/workers/{worker_id}/status")
def report_worker_status(
    worker_id: str,
    update: WorkerStatusUpdateRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Update worker status."""
    done = db.report_worker_status(
        queue_id=queue["_id"],
        worker_id=worker_id,
        report_status=update.status,
    )
    if not done:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR)


@app.delete("/api/v1/queues/me/workers/{worker_id}", status_code=HTTP_204_NO_CONTENT)
def delete_worker(
    worker_id: str,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    cascade_update: bool = True,
    db: DBService = Depends(get_db),
):
    """Delete a worker."""
    deleted_count = db.delete_worker(
        queue_id=queue["_id"], worker_id=worker_id, cascade_update=cascade_update
    )
    if deleted_count == 0:
        raise HTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail="Worker not found",
        )


@app.get("/api/v1/queues/me/workers/{worker_id}", response_model=Worker)
def get_worker(
    worker_id: str,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Get a specific worker by ID."""
    worker = db.get_worker(queue_id=queue["_id"], worker_id=worker_id)
    if not worker:
        raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail="Worker not found")
    return worker
