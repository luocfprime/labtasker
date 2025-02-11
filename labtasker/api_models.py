from datetime import datetime
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field, SecretStr

from labtasker.constants import Priority


class HealthCheckResponse(BaseModel):
    status: str = Field(..., pattern=r"^(healthy|unhealthy)$")
    database: str


class QueueCreateRequest(BaseModel):
    queue_name: str = Field(
        ..., pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100
    )
    password: SecretStr = Field(..., min_length=1, max_length=100)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    def to_request_dict(self):
        """
        Used to form a quest, since password must be revealed
        """
        result = self.model_dump()
        result.update({"password": self.password.get_secret_value()})
        return result


class QueueCreateResponse(BaseModel):
    queue_id: str


class QueueGetResponse(BaseModel):
    queue_id: str
    queue_name: str
    created_at: datetime
    last_modified: datetime
    metadata: Dict[str, Any]


class TaskSubmitRequest(BaseModel):
    """Task submission request."""

    task_name: Optional[str] = None
    args: Optional[Dict[str, Any]] = Field(default_factory=dict)
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    cmd: Optional[Union[str, List[str]]] = None
    heartbeat_timeout: Optional[int] = 60
    task_timeout: Optional[int] = None
    max_retries: Optional[int] = 3
    priority: Optional[int] = Priority.MEDIUM


class TaskFetchRequest(BaseModel):
    worker_id: Optional[str] = None
    eta_max: Optional[str] = None
    start_heartbeat: bool = True
    required_fields: Optional[Dict[str, Any]] = None
    extra_filter: Optional[Dict[str, Any]] = None


class TaskFetchTask(BaseModel):
    task_id: str
    args: Dict[str, Any]
    metadata: Dict[str, Any]
    created_at: datetime
    heartbeat_timeout: Optional[int] = None
    task_timeout: Optional[int] = None


class TaskFetchResponse(BaseModel):
    found: bool = False
    task: Optional[TaskFetchTask] = None


class TaskLsRequest(BaseModel):
    offset: int = 0
    limit: int = 100
    task_id: Optional[str] = None
    task_name: Optional[str] = None
    extra_filter: Optional[Dict[str, Any]] = None


class Task(BaseModel):
    task_id: str = Field(alias="_id")  # Accepts "_id" as an input field
    queue_id: str
    status: str
    task_name: Optional[str]
    created_at: datetime
    start_time: Optional[datetime]
    last_heartbeat: Optional[datetime]
    last_modified: datetime
    heartbeat_timeout: Optional[int]
    task_timeout: Optional[int]
    max_retries: int
    retries: int
    priority: int
    metadata: Dict
    args: Dict
    cmd: str
    summary: Dict
    worker_id: Optional[str]


class TaskLsResponse(BaseModel):
    found: bool = False
    content: List[Task] = Field(default_factory=list)


class TaskSubmitResponse(BaseModel):
    task_id: str


class TaskStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern=r"^(success|failed|cancelled)$")
    summary: Optional[Dict[str, Any]] = Field(default_factory=dict)


class WorkerCreateRequest(BaseModel):
    worker_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    max_retries: Optional[int] = 3


class WorkerCreateResponse(BaseModel):
    worker_id: str


class WorkerStatusUpdateRequest(BaseModel):
    status: str = Field(..., pattern=r"^(active|suspended|failed)$")


class WorkerLsRequest(BaseModel):
    offset: int = 0
    limit: int = 100
    worker_id: Optional[str] = None
    worker_name: Optional[str] = None
    extra_filter: Optional[Dict[str, Any]] = None


class Worker(BaseModel):
    worker_id: str = Field(alias="_id")
    queue_id: str
    status: str
    worker_name: Optional[str]
    metadata: Dict
    retries: int
    max_retries: int
    created_at: datetime
    last_modified: datetime


class WorkerLsResponse(BaseModel):
    found: bool = False
    content: List[Worker] = Field(default_factory=list)


class QueueUpdateRequest(BaseModel):
    new_queue_name: Optional[str] = Field(
        None, pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100
    )
    new_password: Optional[SecretStr] = Field(None, min_length=1, max_length=100)
    metadata_update: Optional[Dict[str, Any]] = Field(default_factory=dict)

    def to_request_dict(self):
        """
        Used to form a quest, since password must be revealed
        """
        result = self.model_dump()
        if self.new_password:
            result.update({"new_password": self.new_password.get_secret_value()})
        return result
