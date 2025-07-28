import warnings
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple, TypeVar, Union

from packaging.version import Version
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from labtasker import __version__
from labtasker.constants import Priority
from labtasker.utils import _disable_check_var, validate_dict_keys


class BaseApiModel(BaseModel):
    """Base API model for all API models."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    unknown_fields: Dict[str, Any] = Field(
        default_factory=dict, exclude=True
    )  # marked as excluded from serialization

    @model_validator(mode="before")
    @classmethod
    def collect_unknown_fields(
        cls, data: Dict[str, Any], info: ValidationInfo
    ) -> Dict[str, Any]:
        if _disable_check_var.get():  # if check is disabled, return data
            return data

        if isinstance(data, dict):
            # Get the set of model field names
            model_field_names = set(cls.model_fields.keys())  # type: ignore

            unknown_fields = {
                k: v for k, v in data.items() if k not in model_field_names
            }

            if unknown_fields:
                warnings.warn(
                    f"Unknown fields provided to {cls.__name__}: {', '.join(unknown_fields.keys())}; "
                    f"It could be that your client and server version mismatch. Try upgrading both to latest versions.",
                    UserWarning,
                )
                data["_unknown_fields"] = unknown_fields

        return data


class BaseRequestModel(BaseApiModel):
    client_version: str = __version__

    @field_validator("client_version")
    def validate_client_version(cls, v, field):
        # make sure it is a valid version
        Version(v)
        return v


class Notification(BaseModel):
    """Server notification such as compatibility warning etc."""

    type: str = Field(..., pattern=r"^(info|warning|error)$")
    level: str = Field(..., pattern=r"^(low|medium|high)$")
    details: Union[str, Dict[str, Any]]


class BaseResponseModel(BaseApiModel):
    notification: Optional[List[Notification]] = None


class MetadataKeyValidateMixin:

    @field_validator("metadata")
    def validate_keys(cls, v, field):
        if v:
            validate_dict_keys(v)
        return v


class ArgsKeyValidateMixin:

    @field_validator("args")
    def validate_keys(cls, v, field):
        if v:
            validate_dict_keys(v)
        return v


class SummaryKeyValidateMixin:

    @field_validator("summary")
    def validate_keys(cls, v, field):
        if v:
            validate_dict_keys(v)
        return v


class HealthCheckResponse(BaseResponseModel):
    status: str = Field(..., pattern=r"^(healthy|unhealthy)$")
    database: str


class QueueCreateRequest(BaseRequestModel, MetadataKeyValidateMixin):
    queue_name: str = Field(
        ..., pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100
    )
    password: SecretStr = Field(..., min_length=1, max_length=100)
    metadata: Optional[Dict[str, Any]] = None

    def to_request_dict(self):
        """
        Used to form a quest, since password must be revealed
        """
        result = self.model_dump()
        result.update({"password": self.password.get_secret_value()})
        return result


class QueueCreateResponse(BaseResponseModel):
    queue_id: str


class QueueGetResponse(BaseResponseModel, MetadataKeyValidateMixin):
    queue_id: str = Field(alias="_id")
    queue_name: str
    created_at: datetime
    last_modified: datetime
    metadata: Dict[str, Any]


class TaskSubmitRequest(
    BaseRequestModel,
    ArgsKeyValidateMixin,
    MetadataKeyValidateMixin,
    SummaryKeyValidateMixin,
):
    """Task submission request."""

    task_name: Optional[str] = Field(
        None, pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100
    )
    args: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    cmd: Optional[Union[str, List[str]]] = None
    heartbeat_timeout: Optional[float] = None
    task_timeout: Optional[int] = None
    max_retries: int = 3
    priority: int = Priority.MEDIUM


T = TypeVar("T", bound="DatetimeSerializationMixin")


class DatetimeSerializationMixin:
    """
    A mixin that enables proper serialization and deserialization of datetime objects
    in the extra_filter field.

    This mixin should be used with BaseModel.
    Example: class MyModel(DatetimeSerializationMixin, BaseModel):
    """

    # Define a model validator to process datetime markers in input data
    @model_validator(mode="before")
    @classmethod
    def process_datetime_markers(cls, data: Any) -> Any:
        """Process incoming data to convert datetime markers in extra_filter field"""
        if (
            isinstance(data, dict)
            and "extra_filter" in data
            and data["extra_filter"] is not None
        ):
            data["extra_filter"] = cls._process_datetime_markers(data["extra_filter"])
        return data

    # Add a field validator for extra_filter field
    @field_validator("extra_filter", mode="before")
    @classmethod
    def validate_extra_filter(
        cls, value: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Validate and process extra_filter field"""
        if value is None:
            return None
        return cls._process_datetime_markers(value)

    @classmethod
    def _process_datetime_markers(cls, obj: Any) -> Any:
        """Process data recursively to convert datetime markers to datetime objects"""
        if isinstance(obj, dict):
            # Check if it's a datetime marker
            if "_dt" in obj and len(obj) == 1 and isinstance(obj["_dt"], str):
                try:
                    return datetime.fromisoformat(obj["_dt"])
                except ValueError:
                    pass
            # Process regular dictionary
            return {k: cls._process_datetime_markers(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [cls._process_datetime_markers(item) for item in obj]
        return obj

    def dump_to_json_dict(self) -> Dict[str, Any]:
        """
        Dump the model to a JSON-serializable dictionary with datetime objects
        in extra_filter converted to {"_dt": iso_format} representation.

        This method doesn't modify the model_config, but provides a way to
        properly serialize datetime objects in the extra_filter field.

        Returns:
            Dict[str, Any]: A JSON-serializable dictionary
        """
        # First get the standard model dump
        data = self.model_dump()  # type: ignore[attr-defined]

        # Process extra_filter field if it exists
        if "extra_filter" in data and data["extra_filter"] is not None:
            data["extra_filter"] = self._process_datetime_objects(data["extra_filter"])

        return data

    def _process_datetime_objects(self, obj: Any) -> Any:
        """Process data recursively to convert datetime objects to markers"""
        if isinstance(obj, dict):
            return {k: self._process_datetime_objects(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._process_datetime_objects(item) for item in obj]
        elif isinstance(obj, datetime):
            return {"_dt": obj.isoformat()}
        elif isinstance(obj, tuple):
            # Convert tuples to lists for JSON serialization
            return [self._process_datetime_objects(item) for item in obj]
        return obj


class TaskFetchRequest(DatetimeSerializationMixin, BaseRequestModel):  # type: ignore[misc]
    worker_id: Optional[str] = None
    eta_max: Optional[str] = None
    heartbeat_timeout: Optional[float] = None
    start_heartbeat: bool = True
    required_fields: Optional[List[str]] = None
    extra_filter: Optional[Dict[str, Any]] = None
    cmd: Optional[Union[str, List[str]]] = None


class Task(
    BaseApiModel,
    ArgsKeyValidateMixin,
    MetadataKeyValidateMixin,
    SummaryKeyValidateMixin,
):
    task_id: str = Field(alias="_id")  # Accepts "_id" as an input field
    queue_id: str
    status: str = Field(..., pattern=r"^(pending|running|success|failed|cancelled)$")
    task_name: Optional[str]
    created_at: datetime
    start_time: Optional[datetime]
    last_heartbeat: Optional[datetime]
    last_modified: datetime
    heartbeat_timeout: Optional[float]
    task_timeout: Optional[int]
    max_retries: int
    retries: int
    priority: int
    metadata: Dict
    args: Dict
    cmd: Optional[Union[str, List[str]]]
    summary: Dict
    worker_id: Optional[str]


class TaskUpdateRequest(
    BaseRequestModel,
    ArgsKeyValidateMixin,
    MetadataKeyValidateMixin,
    SummaryKeyValidateMixin,
):
    """This should be consistent with Task.
    Fields that disallow manual update are commented out.
    """

    # replace_fields: fields that should be overwritten from root fields entirely.
    # Example: When replace_fields = ["args"],
    # suppose the original task.args = {"foo": "bar"}
    # TaskUpdateRequest(args={"a": 1}) will replace the entire args field.
    # The resulting task.args will be task.args = {"a": 1}.
    # If replace_fields = [],
    # TaskUpdateRequest(args={"a": 1}) will only update the args field.
    # The resulting task.args will be task.args = {"foo": "bar", "a": 1}.
    replace_fields: List[str] = Field(default_factory=list)

    # reference from Task
    task_id: str = Field(alias="_id")  # Accepts "_id" as an input field
    # queue_id: str
    status: Optional[str] = Field(
        None, pattern=r"^(pending|running|success|failed|cancelled)$"
    )
    task_name: Optional[str] = Field(
        None, pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100
    )
    # created_at: datetime
    # start_time: Optional[datetime]
    # last_heartbeat: Optional[datetime]
    # last_modified: datetime
    heartbeat_timeout: Optional[float] = None
    task_timeout: Optional[int] = None
    max_retries: Optional[int] = None
    retries: Optional[int] = None
    priority: Optional[int] = None
    metadata: Optional[Dict] = None
    args: Optional[Dict] = None
    cmd: Optional[Union[str, List[str]]] = None
    summary: Optional[Dict] = None
    # worker_id: Optional[str]


class TaskFetchResponse(BaseResponseModel):
    found: bool = False
    task: Optional[Task] = None


class TaskLsRequest(DatetimeSerializationMixin, BaseRequestModel):  # type: ignore[misc]
    offset: int = Field(0, ge=0)
    limit: int = Field(100, gt=0, le=1000)
    task_id: Optional[str] = None
    task_name: Optional[str] = None
    status: Optional[str] = Field(
        None, pattern=r"^(pending|running|success|failed|cancelled)$"
    )
    extra_filter: Optional[Dict[str, Any]] = None
    sort: Optional[List[Tuple[str, int]]] = None  # validate that int must be -1/1

    @field_validator("sort")
    def validate_sort(cls, value):
        if value is not None:
            if not isinstance(value, list):
                raise ValueError("Sort must be a list of tuples.")
            for item in value:
                if not isinstance(item, tuple) or len(item) != 2:
                    raise ValueError(
                        f"Invalid sort format: {item}. Expected (field, order)."
                    )
                field, order = item
                if not isinstance(field, str):
                    raise ValueError(
                        f"Sort field must be a string, got {type(field).__name__}."
                    )
                if order not in (-1, 1):
                    raise ValueError(
                        f"Sort order must be 1 (ascending) or -1 (descending), got {order}."
                    )
        return value


class TaskLsResponse(BaseResponseModel):
    found: bool = False
    content: List[Task] = Field(default_factory=list)


class TaskSubmitResponse(BaseResponseModel):
    task_id: str


class TaskStatusUpdateRequest(BaseRequestModel):
    status: str = Field(..., pattern=r"^(success|failed|cancelled)$")
    worker_id: Optional[str] = None
    summary: Optional[Dict[str, Any]] = None


class WorkerCreateRequest(BaseRequestModel, MetadataKeyValidateMixin):
    worker_name: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    max_retries: Optional[int] = 3


class WorkerCreateResponse(BaseResponseModel):
    worker_id: str


class WorkerStatusUpdateRequest(BaseRequestModel):
    status: str = Field(..., pattern=r"^(active|suspended|crashed)$")


class WorkerLsRequest(DatetimeSerializationMixin, BaseRequestModel):  # type: ignore[misc]
    offset: int = Field(0, ge=0)
    limit: int = Field(100, gt=0, le=1000)
    worker_id: Optional[str] = None
    worker_name: Optional[str] = None
    status: Optional[str] = Field(None, pattern=r"^(active|suspended|crashed)$")
    extra_filter: Optional[Dict[str, Any]] = None
    sort: Optional[List[Tuple[str, int]]] = None  # validate that int must be -1/1

    @field_validator("sort")
    def validate_sort(cls, value):
        if value is not None:
            if not isinstance(value, list):
                raise ValueError("Sort must be a list of tuples.")
            for item in value:
                if not isinstance(item, tuple) or len(item) != 2:
                    raise ValueError(
                        f"Invalid sort format: {item}. Expected (field, order)."
                    )
                field, order = item
                if not isinstance(field, str):
                    raise ValueError(
                        f"Sort field must be a string, got {type(field).__name__}."
                    )
                if order not in (-1, 1):
                    raise ValueError(
                        f"Sort order must be 1 (ascending) or -1 (descending), got {order}."
                    )
        return value


class Worker(BaseApiModel, MetadataKeyValidateMixin):
    worker_id: str = Field(alias="_id")
    queue_id: str
    status: str = Field(..., pattern=r"^(active|suspended|crashed)$")
    worker_name: Optional[str] = Field(
        None, pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100
    )
    metadata: Dict
    retries: int
    max_retries: int
    created_at: datetime
    last_modified: datetime


class WorkerLsResponse(BaseResponseModel):
    found: bool = False
    content: List[Worker] = Field(default_factory=list)


class QueueUpdateRequest(BaseRequestModel):
    new_queue_name: Optional[str] = Field(
        None, pattern=r"^[a-zA-Z0-9_-]+$", min_length=1, max_length=100
    )
    new_password: Optional[SecretStr] = Field(None, min_length=1, max_length=100)
    metadata_update: Optional[Dict[str, Any]] = None

    def to_request_dict(self):
        """
        Used to form a quest, since password must be revealed
        """
        result = self.model_dump()
        if self.new_password:
            result.update({"new_password": self.new_password.get_secret_value()})
        return result


class BaseEventModel(BaseApiModel):
    """Base model for all events"""

    type: Literal["base"] = "base"  # type: ignore[assignment]
    queue_id: str
    timestamp: datetime
    metadata: Dict[str, Any]


class StateTransitionEvent(BaseEventModel):
    """Model for state transition events"""

    type: Literal["state_transition"] = "state_transition"  # type: ignore[assignment]

    entity_type: str = Field(..., pattern=r"^(task|worker)$")  # Validate entity types
    entity_id: str
    old_state: str
    new_state: str
    entity_data: Dict[str, Any]


EventModelTypes = Union[BaseEventModel, StateTransitionEvent]


class EventSubscriptionResponse(BaseApiModel):
    """Response for event subscription"""

    status: str = "connected"
    client_id: str


class EventResponse(BaseApiModel):
    """Model for queue event responses"""

    sequence: int
    timestamp: datetime
    event: EventModelTypes = Field(
        discriminator="type"
    )  # choose which model to use based on type field
