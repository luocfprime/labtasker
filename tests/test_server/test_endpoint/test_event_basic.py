import json

import pytest
from httpx_sse import aconnect_sse
from sse_starlette import ServerSentEvent
from sse_starlette.sse import AppStatus
from starlette.status import HTTP_201_CREATED

from labtasker.api_models import (
    EventResponse,
    EventSubscriptionResponse,
    QueueCreateResponse,
    StateTransitionEvent,
)
from labtasker.server.event_manager import QueueEventManager
from labtasker.server.fsm import EntityType
from labtasker.utils import get_current_time
from tests.fixtures.server import async_test_app


@pytest.fixture(autouse=True)
def reset_appstatus_event():
    # https://github.com/sysid/sse-starlette/issues/59
    # avoid: RuntimeError: <asyncio.locks.Event object at 0x1046a0a30 [unset]> is bound to a different event loop
    AppStatus.should_exit_event = None


@pytest.fixture
async def setup_queue(async_test_app, queue_create_request):
    response = await async_test_app.post(
        "/api/v1/queues", json=queue_create_request.to_request_dict()
    )
    assert response.status_code == HTTP_201_CREATED
    return QueueCreateResponse(**response.json())


async def mock_subscribe_connection(self, client_id: str, disconnect_handle):
    """Mock subscribe that yields a connection event"""
    connection_event = EventSubscriptionResponse(
        status="connected",
        client_id=client_id,
    )
    yield ServerSentEvent(
        data=connection_event.model_dump_json(),
        event="connection",
        id="0",
        retry=300,
    )


async def mock_subscribe_with_ping(self, client_id: str, disconnect_handle):
    """Mock subscribe that yields connection and ping"""
    connection_event = EventSubscriptionResponse(
        status="connected",
        client_id=client_id,
    )
    yield ServerSentEvent(
        data=connection_event.model_dump_json(),
        event="connection",
        id="0",
        retry=300,
    )

    yield ServerSentEvent(event="ping")


async def mock_subscribe_with_state_transition(self, client_id: str, disconnect_handle):
    """Mock subscribe that yields connection and state transition events"""
    # Connection event using EventSubscriptionResponse
    connection_event = EventSubscriptionResponse(
        status="connected",
        client_id=client_id,
    )
    yield ServerSentEvent(
        data=connection_event.model_dump_json(),
        event="connection",
        id="0",
        retry=3000,
    )

    # State transition event using proper models
    state_event = StateTransitionEvent(
        queue_id="test_queue",
        timestamp=get_current_time(),
        metadata={},
        entity_type=EntityType.TASK,
        entity_id="test_task_1",
        old_state="created",
        new_state="pending",
        entity_data={
            "_id": "task-12345",
            "queue_id": "queue-789",
            "status": "PENDING",
            "task_name": "process_data",
            "created_at": "2025-03-13T14:30:45.123Z",
            "start_time": None,
            "last_heartbeat": None,
            "last_modified": "2025-03-13T14:30:45.123Z",
            "heartbeat_timeout": 60,
            "task_timeout": 3600,
            "max_retries": 3,
            "retries": 0,
            "priority": 5,
            "metadata": {
                "user": {"id": "user-456", "email": "test@example.com"},
                "source": "api",
                "tags": ["important", "batch"],
            },
            "args": {
                "input_file": "data.csv",
                "options": {"format": "json", "compress": True, "validate": True},
                "destination": {
                    "type": "s3",
                    "bucket": "my-data-bucket",
                    "path": "processed/2025/03/13/",
                },
            },
            "cmd": "python process_data.py --input={input_file} --output={destination.path} --format={options.format}",
            "summary": {},
            "worker_id": None,
        },
    )

    event_response = EventResponse(
        sequence=1,
        timestamp=get_current_time(),
        event=state_event,
    )

    yield ServerSentEvent(
        data=event_response.model_dump_json(),
        event="event",
        id="1",
    )


@pytest.mark.unit
@pytest.mark.anyio
async def test_basic_connection(async_test_app, setup_queue, auth_headers, monkeypatch):
    monkeypatch.setattr(QueueEventManager, "subscribe", mock_subscribe_connection)

    async with aconnect_sse(
        async_test_app, "GET", "/api/v1/queues/me/events", headers=auth_headers
    ) as event_source:
        async for sse in event_source.aiter_sse():
            if sse.event == "connection":
                connection_data = json.loads(sse.data)
                assert connection_data["status"] == "connected"
                assert "client_id" in connection_data
                break


@pytest.mark.unit
@pytest.mark.anyio
async def test_ping(async_test_app, setup_queue, auth_headers, monkeypatch):
    monkeypatch.setattr(QueueEventManager, "subscribe", mock_subscribe_with_ping)

    events = []
    async with aconnect_sse(
        async_test_app, "GET", "/api/v1/queues/me/events", headers=auth_headers
    ) as event_source:
        async for sse in event_source.aiter_sse():
            events.append(sse)
            if len(events) == 2:  # Connection + Ping
                break

    assert events[0].event == "connection"
    assert events[1].event == "ping"


@pytest.mark.unit
@pytest.mark.anyio
async def test_state_transition(async_test_app, setup_queue, auth_headers, monkeypatch):
    monkeypatch.setattr(
        QueueEventManager, "subscribe", mock_subscribe_with_state_transition
    )

    events = []
    async with aconnect_sse(
        async_test_app, "GET", "/api/v1/queues/me/events", headers=auth_headers
    ) as event_source:
        async for sse in event_source.aiter_sse():
            events.append(sse)
            if len(events) == 2:  # Connection + State Transition
                break

    # Verify connection event
    assert events[0].event == "connection"

    # Verify state transition event
    assert events[1].event == "event"
    event_data = json.loads(events[1].data)
    event = EventResponse(**event_data)
    assert isinstance(event.event, StateTransitionEvent)
    assert event.event.entity_type == "task"
    assert event.event.old_state == "created"
    assert event.event.new_state == "pending"
