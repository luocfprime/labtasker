import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient

from labtasker.dependencies import get_db, verify_queue_auth
from labtasker.server import app

client = TestClient(app)


# Override the database dependency with our mock
@pytest.fixture
def test_app(mock_db):
    """Create test app with mock database."""
    # Store mock _db in app state
    app.state.db = mock_db
    # Override database dependency
    app.dependency_overrides[get_db] = lambda: mock_db
    # Clear any existing overrides for verify_queue_auth
    app.dependency_overrides.pop(verify_queue_auth, None)
    yield client
    # Clean up
    app.dependency_overrides.clear()
    delattr(app.state, "db")


@pytest.fixture
def authenticated_app(test_app, mock_db):
    """Create test app with mock authentication."""
    app.dependency_overrides[verify_queue_auth] = lambda: "test_queue"
    yield test_app
    app.dependency_overrides.pop(verify_queue_auth, None)


@pytest.fixture
def queue_data():
    return {"queue_name": "test_queue", "password": "test_password"}


@pytest.fixture
def task_data():
    return {
        "queue_name": "test_queue",
        "password": "test_password",
        "task_name": "test_task",
        "args": {"param1": 1},
        "metadata": {"tag": "test"},
    }


def test_create_queue(test_app, queue_data):
    response = test_app.post("/api/v1/queues", json=queue_data)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "queue_id" in data


def test_get_queue(authenticated_app, queue_data):
    # Create queue first
    response = authenticated_app.post("/api/v1/queues", json=queue_data)
    assert response.status_code == 200
    queue_id = response.json()["queue_id"]

    response = authenticated_app.get(
        "/api/v1/queues",
        params={
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["queue_id"] == queue_id
    assert data["queue_name"] == queue_data["queue_name"]
    assert "status" in data


def test_delete_queue(authenticated_app, queue_data):
    # Create queue first
    response = authenticated_app.post("/api/v1/queues", json=queue_data)
    assert response.status_code == 200

    response = authenticated_app.delete(
        "/api/v1/queues",
        params={
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_submit_task(authenticated_app, task_data):
    # Create queue first
    response = authenticated_app.post(
        "/api/v1/queues",
        json={
            "queue_name": task_data["queue_name"],
            "password": task_data["password"],
        },
    )
    queue_id = response.json()["queue_id"]

    response = authenticated_app.post("/api/v1/tasks", json=task_data)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "task_id" in data


def test_get_next_task(authenticated_app, queue_data):
    # Create queue first
    authenticated_app.post("/api/v1/queues", json=queue_data)

    # Create a task to fetch
    task_data = {
        "queue_name": queue_data["queue_name"],
        "password": queue_data["password"],
        "task_name": "test_task",
        "args": {"param1": 1},
        "metadata": {"tag": "test"},
    }
    authenticated_app.post("/api/v1/tasks", json=task_data)

    # Create Basic Auth header
    import base64

    credentials = base64.b64encode(
        f"{queue_data['queue_name']}:{queue_data['password']}".encode()
    ).decode()

    response = authenticated_app.get(
        "/api/v1/tasks/next",
        params={
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
            "eta_max": "2h",
            "start_heartbeat": False,
        },
        headers={"Authorization": f"Basic {credentials}"},
    )
    assert response.status_code == 200
    data = response.json()
    # Could be either "success" with task data or "no_task" if task was already taken
    assert data["status"] in ["success", "no_task"]
    if data["status"] == "success":
        assert "task_id" in data
        assert "args" in data
        assert "metadata" in data


def test_ls_tasks(authenticated_app, queue_data):
    # Create queue and task first
    response = authenticated_app.post("/api/v1/queues", json=queue_data)
    assert response.status_code == 200

    task_data = {
        "queue_name": queue_data["queue_name"],
        "password": queue_data["password"],
        "task_name": "test_task",
        "args": {"param1": 1},
    }
    response = authenticated_app.post("/api/v1/tasks", json=task_data)
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    response = authenticated_app.get(
        "/api/v1/tasks",
        params={
            "task_id": task_id,
            "task_name": "test_task",
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["tasks"]) > 0
    assert data["tasks"][0]["task_name"] == "test_task"
    assert data["tasks"][0]["task_id"] == task_id


def test_update_task_status(authenticated_app, queue_data):
    # Create queue and task first
    response = authenticated_app.post("/api/v1/queues", json=queue_data)
    assert response.status_code == 200

    task_data = {
        "queue_name": queue_data["queue_name"],
        "password": queue_data["password"],
        "task_name": "test_task",
        "args": {"param1": 1},
    }
    response = authenticated_app.post("/api/v1/tasks", json=task_data)
    assert response.status_code == 200
    task_id = response.json()["task_id"]

    response = authenticated_app.patch(
        f"/api/v1/tasks/{task_id}",
        params={
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
            "status": "completed",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"


def test_get_queue_unauthorized(test_app, queue_data):
    """Test authentication failure."""
    # Create queue first
    test_app.post("/api/v1/queues", json=queue_data)

    response = test_app.get(
        "/api/v1/queues",
        params={"queue_name": queue_data["queue_name"], "password": "wrong_password"},
    )
    assert response.status_code == 401  # Unauthorized
    assert "Invalid password" in response.json()["detail"]


def test_list_tasks(authenticated_app, queue_data):
    """Test listing tasks with filters."""
    # Create queue and tasks
    response = authenticated_app.post("/api/v1/queues", json=queue_data)

    task_data = {
        "queue_name": queue_data["queue_name"],
        "password": queue_data["password"],
        "task_name": "test_task",
        "args": {"param1": 1},
        "metadata": {"tags": ["test_tag"]},
    }

    # Create multiple tasks
    authenticated_app.post("/api/v1/tasks", json=task_data)

    # Test listing all tasks
    response = authenticated_app.get(
        "/api/v1/tasks",
        params={
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert len(data["tasks"]) > 0
    # Verify tasks belong to the correct queue
    for task in data["tasks"]:
        assert task["queue_name"] == queue_data["queue_name"]
        assert "queue_id" in task

    # Test filtering by status
    response = authenticated_app.get(
        "/api/v1/tasks",
        params={
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
            "status": "created",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert all(task["status"] == "created" for task in data["tasks"])

    # Test filtering by tag
    response = authenticated_app.get(
        "/api/v1/tasks",
        params={
            "queue_name": queue_data["queue_name"],
            "password": queue_data["password"],
            "tag": "test_tag",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert all("test_tag" in task["metadata"]["tags"] for task in data["tasks"])


@pytest.fixture
async def async_client():
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client


def test_create_worker(authenticated_app, queue_args):
    """Test worker creation endpoint."""
    # First create a queue
    response = authenticated_app.post(
        "/api/v1/queues",
        json={
            "queue_name": queue_args["queue_name"],
            "password": queue_args["password"],
        },
    )
    assert response.status_code == 200

    # Create worker
    worker_data = {
        "queue_name": queue_args["queue_name"],
        "worker_name": "test_worker",
        "metadata": {"test": "data"},
        "max_retries": 5,
    }
    response = authenticated_app.post("/api/v1/workers", json=worker_data)
    assert response.status_code == 200
    worker_id = response.json()["worker_id"]

    # Verify worker was created
    response = authenticated_app.get(
        f"/api/v1/workers/{worker_id}", params={"queue_name": queue_args["queue_name"]}
    )
    assert response.status_code == 200
    worker = response.json()
    assert worker["worker_name"] == "test_worker"
    assert worker["status"] == "active"
    assert worker["metadata"] == {"test": "data"}


def test_worker_status_update(authenticated_app, queue_args):
    """Test worker status update endpoint."""
    # Setup: Create queue and worker
    authenticated_app.post(
        "/api/v1/queues",
        json={
            "queue_name": queue_args["queue_name"],
            "password": queue_args["password"],
        },
    )
    response = authenticated_app.post(
        "/api/v1/workers", json={"queue_name": queue_args["queue_name"]}
    )
    worker_id = response.json()["worker_id"]

    # Test suspending worker
    response = authenticated_app.patch(
        f"/api/v1/workers/{worker_id}/status",
        json={"queue_name": queue_args["queue_name"], "status": "suspended"},
    )
    assert response.status_code == 200

    # Verify worker is suspended
    response = authenticated_app.get(
        f"/api/v1/workers/{worker_id}", params={"queue_name": queue_args["queue_name"]}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"

    # Test reactivating worker
    response = authenticated_app.patch(
        f"/api/v1/workers/{worker_id}/status",
        json={"queue_name": queue_args["queue_name"], "status": "active"},
    )
    assert response.status_code == 200

    # Verify worker is active
    response = authenticated_app.get(
        f"/api/v1/workers/{worker_id}", params={"queue_name": queue_args["queue_name"]}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"
