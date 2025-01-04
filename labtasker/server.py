import asyncio
from asyncio import create_task
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional
from uuid import uuid4

import uvicorn
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .database import DatabaseClient
from .dependencies import get_db
from .utils import get_current_time


async def periodic_task(interval_seconds: int):
    """Run a periodic task at specified intervals."""
    while True:
        try:
            db = next(get_db())  # FIXME
            transitioned_tasks = db.handle_timeouts()
            if transitioned_tasks:
                print(f"Transitioned {len(transitioned_tasks)} timed out tasks")
        except Exception as e:
            print(f"Error checking timeouts: {e}")
        await asyncio.sleep(interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Manage application lifespan and background tasks."""
    task = create_task(periodic_task(30))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health_check(db: DatabaseClient = Depends(get_db)):
    """Health check endpoint."""
    try:
        # Check database connection
        db.client.admin.command("ping")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "database": str(e)}


class QueueCreate(BaseModel):
    queue_name: str
    password: str


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
    _id = db.create_queue(queue.queue_name, queue.password)
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

    queue = db.queues.find_one(query)
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

    queue = db.queues.find_one(query)
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
    # queue = db.queues.find_one({"queue_name": task.queue_name})
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
    worker_name: Optional[str] = None,
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

    queue = db.queues.find_one(query)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    task = db.fetch_task(
        queue_name=queue["queue_name"],
        worker_id=str(
            uuid4()
        ),  # FIXME: worker_id should be optional, definitely not like this
        worker_name=worker_name,
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

    queue = db.queues.find_one(queue_query)
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

    tasks = list(db.tasks.find(task_query))
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
    # TODO: need to use db api
    """Update task status (complete, failed, etc)"""
    query = {"_id": task_id}
    if queue_id:
        query["queue_id"] = queue_id
    if queue_name:
        query["queue_name"] = queue_name

    task = db.tasks.find_one_and_update(
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

    task = db.tasks.find_one_and_update(
        query,
        {"$set": {"last_heartbeat": get_current_time()}},
        return_document=True,
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "success"}


if __name__ == "__main__":
    from .config import ServerConfig

    config = ServerConfig()
    uvicorn.run(app, host=config.api_host, port=config.api_port)
