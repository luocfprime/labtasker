import asyncio
from asyncio import create_task
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from uuid import uuid4

import uvicorn
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Body
from pydantic import BaseModel

from .config import ServerConfig
from .database import DatabaseClient, Priority
from .dependencies import get_db, get_verified_queue_dependency
from .utils import get_current_time

config = ServerConfig()


async def periodic_task(db: DatabaseClient, interval_seconds: int):
    """Run a periodic task at specified intervals."""
    while True:
        try:
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
    app.state.db = DatabaseClient(config.mongodb_uri, config.db_name)
    task = create_task(periodic_task(app.state.db, interval_seconds=30))

    yield

    # Cleanup
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if app.state.db:
        app.state.db.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check(db: DatabaseClient = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Check database connection
        db.ping()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


class QueueCreate(BaseModel):
    queue_name: str
    password: str
    metadata: Optional[Dict[str, Any]] = {}


class TaskSubmit(BaseModel):
    """Task submission request."""

    task_name: Optional[str] = None
    args: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = {}
    heartbeat_timeout: Optional[int] = 60
    task_timeout: Optional[int] = None
    max_retries: Optional[int] = 3
    priority: Optional[int] = Priority.MEDIUM


@app.post("/api/v1/queues")
async def create_queue(queue: QueueCreate, db: DatabaseClient = Depends(get_db)):
    """Create a new queue"""
    _id = db.create_queue(
        queue_name=queue.queue_name,
        password=queue.password,
        metadata=queue.metadata,
    )
    return {"status": "success", "queue_id": _id}


@app.get("/api/v1/queues/{queue_id}")
async def get_queue(queue_id: str, db: DatabaseClient = Depends(get_db)):
    """Get queue information. (No authentication required)"""
    queue = db.get_queue(queue_id=queue_id)
    return {
        "queue_id": str(queue["_id"]),
        "queue_name": queue["queue_name"],
        "status": "active",
        "created_at": queue["created_at"],
    }


@app.get("/api/v1/queues")
async def get_queue(queue: Dict[str, Any] = Depends(get_verified_queue_dependency)):
    """Get queue information"""
    return {
        "queue_id": str(queue["_id"]),
        "queue_name": queue["queue_name"],
        "status": "active",
        "created_at": queue["created_at"],
        "last_modified": queue["last_modified"],
        "metadata": queue["metadata"],
    }


@app.delete("/api/v1/queues")
async def delete_queue(
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    cascade_delete: bool = False,
    db: DatabaseClient = Depends(get_db),
):
    """Delete a queue"""
    db.delete_queue(queue_name=queue["queue_name"], cascade_delete=cascade_delete)
    return {"status": "success"}


@app.post("/api/v1/tasks")
async def submit_task(
    task: TaskSubmit,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DatabaseClient = Depends(get_db),
):
    """Submit a task to the queue"""
    task_id = db.create_task(
        queue_name=queue["queue_name"],
        task_name=task.task_name,
        args=task.args,
        metadata=task.metadata,
        heartbeat_timeout=task.heartbeat_timeout,
        task_timeout=task.task_timeout,
        max_retries=task.max_retries,
        priority=task.priority,
    )
    return {"status": "success", "task_id": task_id}


@app.get("/api/v1/tasks/next")
async def get_next_task(
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    worker_id: Optional[str] = None,
    eta_max: Optional[str] = None,
    start_heartbeat: bool = True,
    extra_filter: Optional[Dict[str, Any]] = None,
    db: DatabaseClient = Depends(get_db),
):
    """Get next available task from queue"""
    task = db.fetch_task(
        queue_name=queue["queue_name"],
        worker_id=worker_id,
        eta_max=eta_max,
        start_heartbeat=start_heartbeat,
        extra_filter=extra_filter,
    )
    if not task:
        return {"status": "no_task"}
    task_id = str(task.pop("_id"))
    task["task_id"] = task_id
    return {
        "status": "success",
        "task_id": task_id,
        "args": task["args"],
        "metadata": task["metadata"],
    }


@app.get("/api/v1/tasks")
async def ls_tasks(
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    extra_filter: Optional[Dict[str, Any]] = None,
    limit: Optional[int] = 100,
    db: DatabaseClient = Depends(get_db),
):
    """Get tasks matching the criteria"""
    # Build task query
    task_query = extra_filter or {}
    task_query["queue_id"] = queue["_id"]

    if task_id:
        task_query["_id"] = task_id
    if task_name:
        task_query["task_name"] = task_name

    tasks = db.query_collection(
        queue_name=queue["queue_name"],
        collection_name="tasks",
        query=task_query,
        limit=limit,
    )

    for task in tasks:
        task_id = str(task.pop("_id"))
        task["task_id"] = task_id
    return {"status": "success", "tasks": tasks}


class TaskStatusUpdate(BaseModel):
    status: str
    summary: Optional[Dict[str, Any]] = {}


@app.patch("/api/v1/tasks/{task_id}/status")
async def update_task_status(
    task_id: str,
    update: TaskStatusUpdate,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DatabaseClient = Depends(get_db),
):
    """Report task status (success, failed, cancelled)"""
    done = db.update_task_status(
        queue_name=queue["queue_name"],
        task_id=task_id,
        report_status=update.status,
        summary_update=update.summary,
    )
    return {"status": "success" if done else "error"}


@app.post("/api/v1/tasks/{task_id}/heartbeat")
async def task_heartbeat(
    task_id: str,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DatabaseClient = Depends(get_db),
):
    """Update task heartbeat timestamp."""
    task = db.update_task_heartbeat(
        queue_name=queue["queue_name"],
        task_id=task_id,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}


class WorkerCreate(BaseModel):
    """Worker creation request."""

    worker_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}
    max_retries: Optional[int] = 3


@app.post("/api/v1/workers")
async def create_worker(
    worker: WorkerCreate,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DatabaseClient = Depends(get_db),
):
    """Create a new worker."""
    worker_id = db.create_worker(
        queue_name=queue["queue_name"],
        worker_name=worker.worker_name,
        metadata=worker.metadata,
        max_retries=worker.max_retries,
    )
    return {"status": "success", "worker_id": worker_id}

class WorkerStatusUpdate(BaseModel):
    status: str


@app.patch("/api/v1/workers/{worker_id}/status")
async def update_worker_status(
    worker_id: str,
    update: WorkerStatusUpdate,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DatabaseClient = Depends(get_db),
):
    """Update worker status."""
    db.update_worker_status(
        queue_name=queue["queue_name"],
        worker_id=worker_id,
        report_status=update.status,
    )
    return {"status": "success"}


@app.get("/api/v1/workers/{worker_id}")
async def get_worker(
    worker_id: str,
    queue: Dict[str, Any] = Depends(get_verified_queue_dependency),
    db: DatabaseClient = Depends(get_db),
):
    """Get worker information."""
    workers = db.query_collection(
        queue_name=queue["queue_name"],
        collection_name="workers",
        query={"_id": worker_id},
    )
    
    if not workers or len(workers) == 0:
        raise HTTPException(status_code=404, detail="Worker not found")
    
    worker = workers[0]
    return {
        "worker_id": worker_id,
        "status": worker["status"],
        "worker_name": worker.get("worker_name"),
        "metadata": worker.get("metadata", {}),
        "retries": worker["retries"],
        "created_at": worker["created_at"],
        "last_modified": worker["last_modified"],
    }


if __name__ == "__main__":
    from .config import ServerConfig

    config = ServerConfig()
    uvicorn.run(app, host=config.api_host, port=config.api_port)
