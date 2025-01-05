import base64
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from labtasker.dependencies import get_db
from labtasker.security import get_auth_headers
from labtasker.server import app


@pytest.fixture
def test_app(mock_db):
    """Create test app with mock database."""
    app.state.db = mock_db
    app.dependency_overrides[get_db] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    delattr(app.state, "db")


@pytest.fixture
def queue_data():
    """Test queue data."""
    return {
        "queue_name": "test_queue",
        "password": "test_password",
        "metadata": {"test": "data"},
    }


@pytest.fixture
def task_data(queue_data):
    """Test task data."""
    return {
        "queue_name": queue_data["queue_name"],
        "password": queue_data["password"],
        "task_name": "test_task",
        "args": {"param1": 1},
        "metadata": {"test": "data"},
    }


@pytest.fixture
def auth_headers(queue_data):
    """Create Basic Auth headers."""
    return get_auth_headers(queue_data["queue_name"], queue_data["password"])


class TestQueueEndpoints:
    """Test queue-related endpoints."""

    def test_create_queue(self, test_app, queue_data):
        response = test_app.post("/api/v1/queues", json=queue_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "queue_id" in data

    def test_get_queue(self, test_app, queue_data, auth_headers):
        # Create queue first
        response = test_app.post("/api/v1/queues", json=queue_data)
        queue_id = response.json()["queue_id"]

        response = test_app.get(
            "/api/v1/queues",
            headers=auth_headers,  # Use Basic Auth
        )
        assert response.status_code == 200
        data = response.json()
        assert data["queue_id"] == queue_id
        assert data["queue_name"] == queue_data["queue_name"]


class TestTaskEndpoints:
    """Test task-related endpoints."""

    def test_submit_task(self, test_app, queue_data, task_data, auth_headers):
        """Test task submission."""
        # Create queue first
        test_app.post("/api/v1/queues", json=queue_data)

        response = test_app.post(
            "/api/v1/tasks",
            headers=auth_headers,  # Use Basic Auth
            json={
                "task_name": task_data["task_name"],
                "args": task_data["args"],
                "metadata": task_data["metadata"],
            },
        )
        assert response.status_code == 200

    def test_get_next_task(self, test_app, queue_data, task_data, auth_headers):
        # Setup
        test_app.post("/api/v1/queues", json=queue_data)
        test_app.post("/api/v1/tasks", headers=auth_headers, json=task_data)

        response = test_app.get(
            "/api/v1/tasks/next",
            headers=auth_headers,  # Use Basic Auth
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["success", "no_task"]


class TestWorkerEndpoints:
    """Test worker-related endpoints."""

    def test_create_worker(self, test_app, queue_data, auth_headers):
        # Setup
        test_app.post("/api/v1/queues", json=queue_data)

        response = test_app.post(
            "/api/v1/workers",
            headers=auth_headers,  # Use Basic Auth
            json={
                "worker_name": "test_worker",
                "metadata": {"test": "data"},
            },
        )
        assert response.status_code == 200

    def test_worker_status_update(self, test_app, queue_data, auth_headers):
        """Test worker status update endpoint."""
        # Setup: Create queue and worker
        test_app.post("/api/v1/queues", json=queue_data)

        # Create worker with correct format
        response = test_app.post(
            "/api/v1/workers",
            headers=auth_headers,
            json={
                "worker_name": "test_worker",
                "metadata": {"test": "data"}
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "worker_id" in data
        worker_id = data["worker_id"]

        # Test status updates
        for status in ["suspended", "active"]:
            # Update status
            response = test_app.patch(
                f"/api/v1/workers/{worker_id}/status",
                headers=auth_headers,
                json={"status": status}
            )
            assert response.status_code == 200
            assert response.json()["status"] == "success"

            # Verify worker status was updated
            response = test_app.get(
                f"/api/v1/workers/{worker_id}",
                headers=auth_headers
            )
            assert response.status_code == 200
            data = response.json()
            assert data["worker_id"] == worker_id
            assert data["status"] == status
            assert data["worker_name"] == "test_worker"
            assert data["metadata"] == {"test": "data"}
            assert "retries" in data
            assert "created_at" in data
            assert "last_modified" in data
