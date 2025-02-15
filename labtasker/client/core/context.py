import os
from contextvars import ContextVar
from typing import Optional

from labtasker.api_models import Task

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
    return _current_task_info.get()


def set_task_info(info: Task):
    _current_task_info.set(info)
    set_current_task_id(info.task_id)


def set_current_task_id(task_id: str):
    os.environ["LABTASKER_TASK_ID"] = task_id
    _current_task_id.set(task_id)


def set_current_worker_id(worker_id: str):
    os.environ["LABTASKER_WORKER_ID"] = worker_id
    _current_worker_id.set(worker_id)
