import asyncio
from datetime import datetime, timedelta

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from starlette.status import HTTP_200_OK, HTTP_201_CREATED

from labtasker.api_models import (
    QueueCreateRequest,
    QueueCreateResponse,
    TaskFetchRequest,
    TaskLsRequest,
    TaskSubmitRequest,
)
from labtasker.security import get_auth_headers
from labtasker.server.endpoints import app


async def tick(
    frozen_time,
    delta: timedelta,
    speedup: float = 1000.0,
    cycles: int = 100,
):
    """
    Spins the asyncio event loop while ticking time faster

    Args:
        frozen_time: The time factory to advance
        delta: Elapsed virtual time
        speedup: realtime = delta / speedup
        cycles: cycles to spin
    """
    realtime = delta / speedup

    vt_interval = delta / cycles  # virtual time
    rt_interval = realtime / cycles  # real time

    for _ in range(cycles - 1):
        frozen_time.tick(delta=vt_interval)
        await asyncio.sleep(rt_interval.total_seconds())
    # Final tick to reach exact delta
    remaining = delta - (vt_interval * (cycles - 1))
    frozen_time.tick(delta=remaining)


@pytest.fixture
async def test_app(db_fixture):
    # Depends on db_fixture to ensure db is patched
    # note: you _must_ set `base_url` for relative urls like "/" to work
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


@pytest.fixture
def queue_create_request():
    return QueueCreateRequest(
        queue_name="test_queue",
        password=SecretStr("test_password"),
        metadata={"tag": "test"},
    )


@pytest.fixture
def task_submit_request():
    """Test task data."""
    return TaskSubmitRequest(
        task_name="test_task",
        args={"param1": 1},
        metadata={"test": "data"},
    )


@pytest.fixture
def auth_headers(queue_create_request):
    return get_auth_headers(
        queue_create_request.queue_name, queue_create_request.password
    )


@pytest.fixture
async def setup_queue(test_app, queue_create_request):
    response = await test_app.post(
        "/api/v1/queues", json=queue_create_request.to_request_dict()
    )
    assert (
        response.status_code == HTTP_201_CREATED
    ), f"Got {response.status_code}, {response.json()}"
    queue = QueueCreateResponse(**response.json())
    return queue


@pytest.mark.integration
@pytest.mark.unit
@pytest.mark.anyio
class TestTaskEndpoints:

    async def test_worker_task_timeout(
        self, test_app, setup_queue, auth_headers, mock_get_current_time
    ):
        """This testcase see if heartbeat timeout can be properly handled"""
        # 1. Create a task
        response = await test_app.post(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            json=TaskSubmitRequest(
                task_name="test_task",
                args={"param1": 1},
                heartbeat_timeout=99999999,  # long enough so that heartbeat timeout is not reached
            ).model_dump(),
        )
        assert response.status_code == HTTP_201_CREATED, f"{response.json()}"

        # 2. Fetch task & timeout & retry loop
        start = datetime(2025, 1, 1, 0, 0, 0)
        mock_get_current_time.set_current_time(start)
        for i in range(3):  # 3 retries
            response = await test_app.post(
                "/api/v1/queues/me/tasks/next",
                headers=auth_headers,
                json=TaskFetchRequest(
                    eta_max="1min",  # set 1 min timeout for testing
                    start_heartbeat=True,
                    extra_filter={"task_name": "test_task"},
                ).model_dump(),
            )
            assert response.status_code == HTTP_200_OK, f"{response.json()}"

            await tick(mock_get_current_time, timedelta(minutes=2))

            # get status
            response = await test_app.get(
                "/api/v1/queues/me/tasks",
                headers=auth_headers,
                params=TaskLsRequest(
                    task_name="test_task",
                ).model_dump(),
            )
            assert response.status_code == HTTP_200_OK, f"{response.json()}"
            assert response.json()["tasks"][0]["retries"] == i + 1

            if i < 2:  # first 2 fails enters retry "pending" status
                assert response.json()["tasks"][0]["status"] == "pending"
            else:  # 3rd fail crashes
                assert response.json()["tasks"][0]["status"] == "failed"
