import asyncio
from asyncio import create_task
from contextlib import asynccontextmanager
from typing import Any, Dict, List

from fastapi import Depends, FastAPI, HTTPException
from starlette.status import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from labtasker.api_models import (
    QueueCreateRequest,
    QueueCreateResponse,
    QueueGetResponse,
    Task,
    TaskFetchRequest,
    TaskFetchResponse,
    TaskFetchTask,
    TaskLsRequest,
    TaskLsRespose,
    TaskStatusUpdateRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
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
from labtasker.utils import parse_obj_as


async def periodic_task(interval_seconds: float):
    """Run a periodic task at specified intervals."""
    while True:
        try:
            # print(
            #     f"now: {get_current_time()}, current_event_loop: {asyncio.get_running_loop().__hash__()}"
            # )
            db = get_db()
            transitioned_tasks = db.handle_timeouts()
            if transitioned_tasks:
                print(f"Transitioned {len(transitioned_tasks)} timed out tasks")
        except Exception as e:
            print(f"Error checking timeouts: {e}")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan and background tasks."""
    # Setup
    config = get_server_config()
    task = create_task(periodic_task(config.periodic_task_interval))

    yield

    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health_check(db: DBService = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Check database connection
        db.ping()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


@app.post("/api/v1/queues", status_code=HTTP_201_CREATED)
def create_queue(queue: QueueCreateRequest, db: DBService = Depends(get_db)):
    """Create a new queue"""
    queue_id = db.create_queue(
        queue_name=queue.queue_name,
        password=queue.password.get_secret_value(),
        metadata=queue.metadata,
    )
    return QueueCreateResponse(queue_id=queue_id)


@app.get("/api/v1/queues/me")
def get_queue(queue: Dict[str, Any] = Depends(get_verified_queue_dependency)):
    """Get queue information"""
    return QueueGetResponse(
        queue_id=queue["_id"],
        queue_name=queue["queue_name"],
        created_at=queue["created_at"],
        last_modified=queue["last_modified"],
        metadata=queue["metadata"],
    )


# TODO: update queue


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


@app.get("/api/v1/queues/me/tasks")
def ls_tasks(
    task_request: TaskLsRequest = Depends(),
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
        return TaskLsRespose(found=False)

    return TaskLsRespose(found=True, tasks=parse_obj_as(List[Task], tasks))


@app.post("/api/v1/queues/me/tasks/next")
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
        start_heartbeat=task_request.start_heartbeat,
        required_fields=task_request.required_fields,
        extra_filter=task_request.extra_filter,
    )

    if not task:
        return TaskFetchResponse(found=False)
    return TaskFetchResponse(
        found=True,
        task=TaskFetchTask(
            task_id=task["_id"],
            args=task["args"],
            metadata=task["metadata"],
            created_at=task["created_at"],
            heartbeat_timeout=task["heartbeat_timeout"],
            task_timeout=task["task_timeout"],
        ),
    )


@app.post("/api/v1/queues/me/tasks/{task_id}/status")
def report_task_status(
    task_id: str,
    update: TaskStatusUpdateRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Report task status (success, failed, cancelled)"""
    done = db.report_task_status(
        queue_id=queue["_id"],
        task_id=task_id,
        report_status=update.status,
        summary_update=update.summary,
    )
    if not done:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR)


@app.post("/api/v1/queues/me/tasks/{task_id}/heartbeat")
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


# TODO: delete task


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


@app.get("/api/v1/queues/me/workers")
def ls_worker(
    worker_request: WorkerLsRequest = Depends(),
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

    return WorkerLsResponse(found=True, workers=parse_obj_as(List[Worker], workers))


@app.post("/api/v1/queues/me/workers/{worker_id}/status")
def report_worker_status(
    worker_id: str,
    update: WorkerStatusUpdateRequest,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DBService = Depends(get_db),
):
    """Update worker status."""
    done = db.report_worker_status(
        queue_name=queue["queue_name"],
        worker_id=worker_id,
        report_status=update.status,
    )
    if not done:
        raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR)


# TODO: delete worker
