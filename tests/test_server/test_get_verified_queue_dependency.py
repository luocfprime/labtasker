from typing import Any, Dict

import pytest
from fastapi import Depends, FastAPI
from pydantic import SecretStr
from starlette.status import HTTP_200_OK, HTTP_401_UNAUTHORIZED
from starlette.testclient import TestClient

from labtasker.api_models import QueueCreateRequest
from labtasker.security import get_auth_headers
from labtasker.server.dependencies import get_verified_queue_dependency

app = FastAPI()

# Mark the entire file as integration and unit tests
pytestmark = [pytest.mark.integration, pytest.mark.unit]


# Endpoint to test the dependency
@app.get("/test-queue")
def _(queue: Dict[str, Any] = Depends(get_verified_queue_dependency)):
    return {"queue_id": queue["_id"], "queue_name": queue["queue_name"]}


@pytest.fixture
def test_app(db_fixture):
    return TestClient(app)


@pytest.fixture
def setup_queue(db_fixture):
    queue_data = QueueCreateRequest(
        queue_name="test_queue",
        password=SecretStr("test_password"),
        metadata={"key": "value"},
    )
    queue_id = db_fixture.create_queue(
        queue_name=queue_data.queue_name,
        password=queue_data.password.get_secret_value(),
        metadata=queue_data.metadata,
    )
    return queue_id, queue_data


def test_verified_queue_dependency_success(test_app, setup_queue):
    queue_id, queue_data = setup_queue
    auth_headers = get_auth_headers(queue_data.queue_name, queue_data.password)
    response = test_app.get("/test-queue", headers=auth_headers)
    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert data["queue_id"] == queue_id
    assert data["queue_name"] == queue_data.queue_name


def test_verified_queue_dependency_invalid_credentials(test_app):
    auth_headers = get_auth_headers("invalid_queue", SecretStr("wrong_password"))
    response = test_app.get("/test-queue", headers=auth_headers)
    assert response.status_code == HTTP_401_UNAUTHORIZED


def test_verified_queue_dependency_missing_credentials(test_app):
    response = test_app.get("/test-queue")
    assert response.status_code == HTTP_401_UNAUTHORIZED


def test_verified_queue_dependency_with_queue_id(test_app, setup_queue):
    queue_id, queue_data = setup_queue
    auth_headers = get_auth_headers(queue_id, queue_data.password)
    response = test_app.get("/test-queue", headers=auth_headers)
    assert response.status_code == HTTP_200_OK
    data = response.json()
    assert data["queue_id"] == queue_id
    assert data["queue_name"] == queue_data.queue_name
