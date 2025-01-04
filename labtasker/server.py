import asyncio
from asyncio import create_task
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from uuid import uuid4

import uvicorn
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .config import ServerConfig
from .database import DatabaseClient
from .dependencies import get_db
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
    queue_name: str
    password: str
    task_name: Optional[str] = None
    args: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = {}
    heartbeat_timeout: Optional[int] = 60
    task_timeout: Optional[int] = None


@app.post("/api/v1/queues")
async def create_queue(queue: QueueCreate, db: DatabaseClient = Depends(get_db)):
    """Create a new queue"""
    _id = db.create_queue(
        queue_name=queue.queue_name,
        password=queue.password,
        metadata=queue.metadata,
    )
    return {"status": "success", "queue_id": _id}


@app.get("/api/v1/queues")
async def get_queue(
    password: str,
    queue_id: Optional[str] = None,
    queue_name: Optional[str] = None,
    db: DatabaseClient = Depends(get_db),
):
    """Get queue information"""
    if not queue_id and not queue_name:
        raise HTTPException(
            status_code=422, detail="Either queue_id or queue_name must be provided"
        )

    query = {}
    if queue_id:
        query["_id"] = ObjectId(queue_id)
    if queue_name:
        query["queue_name"] = queue_name

    queue = db._queues.find_one(query)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    # Verify password
    if not db.security.verify_password(password, queue["password"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    return {
        "queue_id": str(queue["_id"]),
        "queue_name": queue["queue_name"],
        "status": "active",
        "created_at": queue["created_at"],
    }


@app.delete("/api/v1/queues")
async def delete_queue(
    password: str,
    queue_id: Optional[str] = None,
    queue_name: Optional[str] = None,
    db: DatabaseClient = Depends(get_db),
):
    """Delete a queue"""
    if not queue_id and not queue_name:
        raise HTTPException(
            status_code=422, detail="Either queue_id or queue_name must be provided"
        )

    # Find and verify queue
    query = {}
    if queue_id:
        query["_id"] = queue_id
    if queue_name:
        query["queue_name"] = queue_name

    queue = db._queues.find_one(query)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    # Verify password
    if not db.security.verify_password(password, queue["password"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    return {"status": "success"}


@app.post("/api/v1/tasks")
async def submit_task(
    task: TaskSubmit,
    db: DatabaseClient = Depends(get_db),
):
    """Submit a task to the queue"""
    # queue = _db.queues.find_one({"queue_name": task.queue_name})
    # if not queue:
    #     raise HTTPException(status_code=404, detail="Queue not found")

    task_id = db.create_task(
        queue_name=task.queue_name,
        task_name=task.task_name,
        args=task.args,
        metadata=task.metadata,
        heartbeat_timeout=task.heartbeat_timeout,
        task_timeout=task.task_timeout,
    )
    return {"status": "success", "task_id": task_id}


@app.get("/api/v1/tasks/next")
async def get_next_task(
    db: DatabaseClient = Depends(get_db),
    queue_id: Optional[str] = None,
    queue_name: Optional[str] = None,
    worker_id: Optional[str] = None,
    eta_max: str = "2h",
    start_heartbeat: bool = False,
):
    """Get next available task from queue"""
    if not queue_id and not queue_name:
        raise HTTPException(
            status_code=422, detail="Either queue_id or queue_name must be provided"
        )

    query = {}
    if queue_id:
        query["_id"] = queue_id
    if queue_name:
        query["queue_name"] = queue_name

    queue = db._queues.find_one(query)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    task = db.fetch_task(
        queue_name=queue["queue_name"],
        worker_id=str(
            uuid4()
        ),  # FIXME: worker_id should be optional, definitely not like this
        eta_max=eta_max,
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
    password: str,
    queue_id: Optional[str] = None,
    queue_name: Optional[str] = None,
    task_id: Optional[str] = None,
    task_name: Optional[str] = None,
    db: DatabaseClient = Depends(get_db),
):
    """Get tasks matching the criteria"""
    if not queue_id and not queue_name:
        raise HTTPException(
            status_code=422, detail="Either queue_id or queue_name must be provided"
        )

    # Verify queue access first
    queue_query = {}
    if queue_id:
        queue_query["_id"] = ObjectId(queue_id)
    if queue_name:
        queue_query["queue_name"] = queue_name

    queue = db._queues.find_one(queue_query)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")
    if not db.security.verify_password(password, queue["password"]):
        raise HTTPException(status_code=401, detail="Invalid password")

    # Build task query
    task_query = {
        **{
            k: v
            for k, v in {
                "_id": task_id,
                "task_name": task_name,
                "queue_id": queue_id,
                "queue_name": queue_name,
            }.items()
            if v is not None
        }
    }

    tasks = list(db._tasks.find(task_query))
    for task in tasks:
        task_id = str(task.pop("_id"))
        task["task_id"] = task_id
        # Ensure queue_id is a string
        if "queue_id" in task:
            task["queue_id"] = str(task["queue_id"])

    return {"status": "success", "tasks": tasks}


@app.patch("/api/v1/tasks/{task_id}")
async def update_task_status(
    task_id: str,
    status: str,
    queue_id: Optional[str] = None,
    queue_name: Optional[str] = None,
    summary: Optional[Dict[str, Any]] = None,
    db: DatabaseClient = Depends(get_db),
):
    # TODO: need to use _db api
    """Update task status (complete, failed, etc)"""
    query = {"_id": task_id}
    if queue_id:
        query["queue_id"] = queue_id
    if queue_name:
        query["queue_name"] = queue_name

    task = db._tasks.find_one_and_update(
        query,
        {
            "$set": {
                "status": status,
                "summary": summary or {},
                "last_modified": get_current_time(),
            }
        },
        return_document=True,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}


@app.post("/api/v1/tasks/{task_id}/heartbeat")
async def task_heartbeat(
    task_id: str,
    queue_id: Optional[str] = None,
    queue_name: Optional[str] = None,
    db: DatabaseClient = Depends(get_db),
):
    """Update task heartbeat timestamp."""
    query = {"_id": task_id}
    if queue_id:
        query["queue_id"] = queue_id
    if queue_name:
        query["queue_name"] = queue_name

    task = db._tasks.find_one_and_update(
        query,
        {"$set": {"last_heartbeat": get_current_time()}},
        return_document=True,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}


class WorkerCreate(BaseModel):
    """Worker creation request."""

    queue_name: str
    worker_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = {}
    max_retries: Optional[int] = 3


class WorkerStatus(BaseModel):
    """Worker status update request."""

    queue_name: str
    status: str  # One of: 'active', 'suspended'


@app.post("/api/v1/workers")
async def create_worker(worker: WorkerCreate, db: DatabaseClient = Depends(get_db)):
    """Create a new worker."""
    worker_id = db.create_worker(
        queue_name=worker.queue_name,
        worker_name=worker.worker_name,
        metadata=worker.metadata,
        max_retries=worker.max_retries,
    )
    return {"status": "success", "worker_id": worker_id}


@app.patch("/api/v1/workers/{worker_id}/status")
async def update_worker_status(
    worker_id: str, status: WorkerStatus, db: DatabaseClient = Depends(get_db)
):
    """Update worker status."""
    db.update_worker_status(
        queue_name=status.queue_name,
        worker_id=worker_id,
        report_status=status.status,
    )
    return {"status": "success"}


@app.get("/api/v1/workers/{worker_id}")
async def get_worker(
    worker_id: str, queue_name: str, db: DatabaseClient = Depends(get_db)
):
    """Get worker information."""
    queue = db._get_queue_by_name(queue_name)
    worker = db._workers.find_one({"_id": worker_id, "queue_id": queue["_id"]})
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not found")

    return {
        "worker_id": worker_id,
        "queue_name": queue_name,
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
