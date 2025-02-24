import json
import os
from contextvars import ContextVar
from typing import Optional

from labtasker.api_models import Task
from labtasker.client.core.exceptions import LabtaskerRuntimeError
from labtasker.client.core.paths import get_labtasker_log_dir

_current_worker_id: ContextVar[Optional[str]] = ContextVar(
    "worker_id", default=os.environ.get("LABTASKER_WORKER_ID", None)
)
_current_task_id: ContextVar[Optional[str]] = ContextVar(
    "task_id", default=os.environ.get("LABTASKER_TASK_ID", None)
)
_current_task_info: ContextVar[Optional[Task]] = ContextVar("task_info", default=None)


def current_worker_id():
    return _current_worker_id.get()


def current_task_id():
    return _current_task_id.get()


def task_info() -> Task:
    """Get current task info"""
    if _current_task_info.get() is None:  # perhaps called from a job subprocess
        # Try to load it from run dir
        try:
            with open(get_labtasker_log_dir() / "task_info.json", "r") as f:
                _current_task_info.set(Task(**json.load(f)))
        except Exception as e:
            raise LabtaskerRuntimeError(
                "Could not load task info from run dir. This is likely because the task was not run by labtasker."
            ) from e

    return _current_task_info.get()


def set_task_info(info: Task):
    _current_task_info.set(info)
    set_current_task_id(info.task_id)


def set_current_task_id(task_id: str):
    os.environ["LABTASKER_TASK_ID"] = task_id
    _current_task_id.set(task_id)


def set_current_worker_id(worker_id: Optional[str]):
    os.environ["LABTASKER_WORKER_ID"] = worker_id if worker_id else ""
    _current_worker_id.set(worker_id)
