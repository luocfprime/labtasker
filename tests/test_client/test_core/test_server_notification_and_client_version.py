import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.status import HTTP_201_CREATED

from labtasker import __version__
from labtasker.api_models import (
    HealthCheckResponse,
    Notification,
    QueueCreateRequest,
    QueueCreateResponse,
)
from labtasker.client.core.api import create_queue, health_check
from labtasker.security import get_auth_headers

pytestmark = [pytest.mark.unit]

app = FastAPI()


@app.get("/health/full")
def mock_health():
    return HealthCheckResponse(
        status="healthy",
        database="connected",
        notification=[
            Notification(type="info", level="medium", details="Test notification info.")
        ],
    )


@app.post("/api/v1/queues", status_code=HTTP_201_CREATED)
def mock_create_queue(queue: QueueCreateRequest):
    """Create a new queue"""
    assert queue.client_version == __version__
    return QueueCreateResponse(
        queue_id="test-queue-id",
        notification=[
            Notification(type="info", level="medium", details=queue.client_version)
        ],
    )


@pytest.fixture
def test_app_():
    return TestClient(app)


@pytest.fixture(autouse=True)
def patch_up(monkeypatch, client_config, test_app_):
    """The refresh_heartbeat endpoint should be patched"""
    auth_headers = get_auth_headers(
        client_config.queue.queue_name, client_config.queue.password
    )
    test_app_.headers.update(
        {**auth_headers, "Content-Type": "application/json"},
    )
    monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app_)


def test_server_notifications(capture_output):
    health_check()

    assert "Test notification info." in capture_output.stdout


def test_server_get_client_version(capture_output):
    resp = create_queue(queue_name="test-queue-name", password="test-password")
    assert resp.notification[0].details == __version__, resp
