from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from freezegun import freeze_time
from pydantic import SecretStr, ValidationError
from pytest_asyncio import fixture
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_500_INTERNAL_SERVER_ERROR,
)

from labtasker.api_models import (
    QueueCreateRequest,
    QueueCreateResponse,
    QueueGetResponse,
    Task,
    TaskFetchRequest,
    TaskFetchResponse,
    TaskFetchTask,
    TaskLsRequest,
    TaskLsRespose,
    TaskStatusUpdateRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
    Worker,
    WorkerCreateRequest,
    WorkerCreateResponse,
    WorkerLsRequest,
    WorkerLsResponse,
    WorkerStatusUpdateRequest,
)
from labtasker.security import get_auth_headers
from labtasker.server.dependencies import get_db
from labtasker.server.server import app


@pytest.fixture
def test_app(db_fixture):
    """Create test app with mock database."""
    app.state.db = db_fixture
    app.dependency_overrides[get_db] = lambda: db_fixture
    yield TestClient(app)
    app.dependency_overrides.clear()
    delattr(app.state, "db")


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


@fixture
def setup_queue(test_app, queue_create_request):
    response = test_app.post(
        "/api/v1/queues", json=queue_create_request.to_request_dict()
    )
    assert (
        response.status_code == HTTP_201_CREATED
    ), f"Got {response.status_code}, {response.json()}"
    queue = QueueCreateResponse(**response.json())
    return queue


@pytest.mark.integration
@pytest.mark.unit
class TestQueueEndpoints:
    """
    Queue CRUD
    """

    def test_create_queue(self, test_app, queue_create_request):
        response = test_app.post(
            "/api/v1/queues", json=queue_create_request.to_request_dict()
        )
        assert (
            response.status_code == HTTP_201_CREATED
        ), f"Got {response.status_code}, {response.json()}"
        assert QueueCreateResponse(**response.json())

    def test_get_queue(self, test_app, queue_create_request, auth_headers):
        # First create a queue
        test_app.post("/api/v1/queues", json=queue_create_request.to_request_dict())

        # Then get the queue info
        response = test_app.get("/api/v1/queues/me", headers=auth_headers)

        assert response.status_code == HTTP_200_OK
        data = QueueGetResponse(**response.json())
        assert data.queue_name == queue_create_request.queue_name
        assert data.metadata == queue_create_request.metadata

    def test_get_queue_unauthorized(self, test_app):
        response = test_app.get("/api/v1/queues/me")
        assert response.status_code == HTTP_401_UNAUTHORIZED

    def test_get_queue_wrong_credentials(self, test_app, queue_create_request):
        # Create queue first
        test_app.post("/api/v1/queues", json=queue_create_request.to_request_dict())

        # Try to get with wrong password
        wrong_headers = get_auth_headers(
            queue_create_request.queue_name, SecretStr("wrong_password")
        )
        response = test_app.get("/api/v1/queues/me", headers=wrong_headers)
        assert response.status_code == HTTP_401_UNAUTHORIZED

    def test_delete_queue_without_cascade(
        self, test_app, queue_create_request, auth_headers
    ):
        # First create a queue
        test_app.post("/api/v1/queues", json=queue_create_request.to_request_dict())

        # Delete the queue
        response = test_app.delete("/api/v1/queues/me", headers=auth_headers)
        assert response.status_code == HTTP_204_NO_CONTENT

        # Verify queue is deleted by trying to get it
        get_response = test_app.get("/api/v1/queues/me", headers=auth_headers)
        assert get_response.status_code == 401

    def test_delete_queue_with_cascade(
        self, test_app, queue_create_request, auth_headers, task_submit_request
    ):
        # Create queue
        test_app.post("/api/v1/queues", json=queue_create_request.to_request_dict())

        # Add a task to the queue
        test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )

        # Delete queue with cascade
        response = test_app.delete(
            "/api/v1/queues/me", headers=auth_headers, params={"cascade_delete": True}
        )
        assert response.status_code == HTTP_204_NO_CONTENT, f"{response.json()}"


@pytest.mark.integration
@pytest.mark.unit
class TestTaskEndpoints:

    def test_submit_task(
        self, test_app, setup_queue, auth_headers, task_submit_request
    ):
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED
        data = TaskSubmitResponse(**response.json())
        assert data.task_id is not None

    def test_fetch_task(self, test_app, setup_queue, auth_headers, task_submit_request):
        # Submit a task first
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED

        response = test_app.post(
            "/api/v1/queues/me/tasks/next",
            headers=auth_headers,
            json=TaskFetchRequest(
                start_heartbeat=True,
                extra_filter={"task_name": task_submit_request.task_name},
            ).model_dump(),
        )

        assert response.status_code == HTTP_200_OK, f"{response.json()}"
        task = TaskFetchResponse(**response.json())
        assert task.found is True
        assert task.task.args == task_submit_request.args
        assert task.task.metadata == task_submit_request.metadata

    def test_ls_tasks(self, test_app, setup_queue, auth_headers):
        for i in range(10):
            test_app.post(
                "/api/v1/queues/me/tasks",
                json=TaskSubmitRequest(
                    task_name=f"test_task_{i}",
                    args={"param1": 1},
                ).model_dump(),
                headers=auth_headers,
            )

        # Test 1. list tasks by limit and offset
        response = test_app.get(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            params=TaskLsRequest(offset=0, limit=5).model_dump(),
        )
        assert response.status_code == HTTP_200_OK, f"{response.json()}"
        data = TaskLsRespose(**response.json())
        assert data.found is True
        assert len(data.tasks) == 5
        for i, task in enumerate(data.tasks):
            assert task.task_name == f"test_task_{i}"

        # get next 5
        response = test_app.get(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            params=TaskLsRequest(offset=5, limit=5).model_dump(),
        )
        assert response.status_code == HTTP_200_OK, f"{response.json()}"
        data = TaskLsRespose(**response.json())
        assert data.found is True
        assert len(data.tasks) == 5
        for i, task in enumerate(data.tasks):
            assert task.task_name == f"test_task_{i + 5}"

    def test_report_task_status(
        self, test_app, setup_queue, auth_headers, task_submit_request
    ):
        # Submit a task first
        test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        # Fetch task
        response = test_app.post(
            "/api/v1/queues/me/tasks/next",
            headers=auth_headers,
            json=TaskFetchRequest(
                start_heartbeat=True,
                extra_filter={"task_name": task_submit_request.task_name},
            ).model_dump(),
        )
        assert response.status_code == HTTP_200_OK, f"{response.json()}"

        task = TaskFetchResponse(**response.json()).task
        task_id = task.task_id

        # update status
        response = test_app.post(
            f"/api/v1/queues/me/tasks/{task_id}/status",
            headers=auth_headers,
            json=TaskStatusUpdateRequest(status="success").model_dump(),
        )
        assert response.status_code == HTTP_200_OK, f"{response.json()}"

        # query using ls tasks
        response = test_app.get(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            params=TaskLsRequest(task_name=task_submit_request.task_name).model_dump(),
        )

        assert response.status_code == HTTP_200_OK, f"{response.json()}"
        data = TaskLsRespose(**response.json())
        assert data.found is True
        assert data.tasks[0].status == "completed"

        # test with illegal status
        with pytest.raises(ValidationError) as exc:
            test_app.post(
                f"/api/v1/queues/me/tasks/{task_id}/status",
                headers=auth_headers,
                json=TaskStatusUpdateRequest(status="illegal").model_dump(),
            )

    def test_refresh_task_heartbeat(self, test_app, setup_queue, auth_headers):
        # 1. Submit a task first
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=TaskSubmitRequest(
                task_name="test_task",
                args={"param1": 1},
                heartbeat_timeout=60,
            ).model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED, f"{response.json()}"

        start = datetime.now()
        tolerance = timedelta(seconds=1)
        with freeze_time(start) as frozen_time:
            # 2. Fetch task
            response = test_app.post(
                "/api/v1/queues/me/tasks/next",
                headers=auth_headers,
                json=TaskFetchRequest(
                    start_heartbeat=True,
                    extra_filter={"task_name": "test_task"},
                ).model_dump(),
            )

            frozen_time.tick(timedelta(seconds=30))

            # 3. Refresh heartbeat
            response = test_app.post(
                f"/api/v1/queues/me/tasks/{response.json()['task']['task_id']}/heartbeat",
                headers=auth_headers,
            )
            assert response.status_code == HTTP_200_OK, f"{response.json()}"

            # 4. Check heartbeat timestamp via ls
            response = test_app.get(
                "/api/v1/queues/me/tasks",
                headers=auth_headers,
                params=TaskLsRequest(
                    task_name="test_task",
                ).model_dump(),
            )
            assert response.status_code == HTTP_200_OK, f"{response.json()}"
            data = TaskLsRespose(**response.json())
            assert data.tasks[0].last_heartbeat is not None
            assert (
                abs(
                    data.tasks[0].last_heartbeat.timestamp()
                    - (start + timedelta(seconds=30)).timestamp()
                )
                <= tolerance.total_seconds()
            )


@pytest.mark.integration
@pytest.mark.unit
class TestWorkerEndpoints:
    def test_create_worker(self, test_app, setup_queue, auth_headers):
        response = test_app.post(
            "/api/v1/queues/me/workers",
            headers=auth_headers,
            json=WorkerCreateRequest(
                worker_name="test_worker",
                max_retries=3,
                metadata={"tag": "test"},
            ).model_dump(),
        )
        assert response.status_code == HTTP_201_CREATED, f"{response.json()}"
        data = WorkerCreateResponse(**response.json())
        assert data.worker_id is not None

    def test_multi_failure_worker_suspend(self, test_app, setup_queue, auth_headers):
        """Test when worker fails after max-retries, the queue stops assigning tasks to it."""
        # 1. Create a worker
        worker_id = test_app.post(
            "/api/v1/queues/me/workers",
            headers=auth_headers,
            json=WorkerCreateRequest(
                worker_name="test_worker",
                max_retries=3,
                metadata={"test": "data"},
            ).model_dump(),
        ).json()["worker_id"]

        # 2. Create tasks
        for i in range(5):
            test_app.post(
                "/api/v1/queues/me/tasks",
                headers=auth_headers,
                json=TaskSubmitRequest(
                    task_name=f"test_task_{i}",
                    args={"param1": 1},
                    heartbeat_timeout=60,
                ).model_dump(),
            )

        # 3. Fetch tasks and crash them (for 3 max retries)
        for i in range(3):
            # Fetch
            response = test_app.post(
                "/api/v1/queues/me/tasks/next",
                headers=auth_headers,
                json=TaskFetchRequest(
                    worker_id=worker_id,
                    start_heartbeat=True,
                ).model_dump(),
            )
            assert response.status_code == HTTP_200_OK, f"{response.json()}"
            # Crash
            response = test_app.post(
                f"/api/v1/queues/me/tasks/{response.json()['task']['task_id']}/status",
                headers=auth_headers,
                json=TaskStatusUpdateRequest(status="failed").model_dump(),
            )
            assert response.status_code == HTTP_200_OK, f"{response.json()}"

        # The worker should be suspended by now.
        # Get worker from ls api
        response = test_app.get(
            "/api/v1/queues/me/workers",
            headers=auth_headers,
            params=WorkerLsRequest(worker_id=worker_id).model_dump(),
        )
        assert response.status_code == HTTP_200_OK, f"{response.json()}"
        worker_ls = WorkerLsResponse(**response.json())
        assert worker_ls.workers[0].status == "crashed"

        # Try to fetch a task using the crashed worker
        response = test_app.post(
            "/api/v1/queues/me/tasks/next",
            headers=auth_headers,
            json=TaskFetchRequest(
                worker_id=worker_id,
                start_heartbeat=True,
            ).model_dump(),
        )
        assert response.status_code == HTTP_403_FORBIDDEN, f"{response.json()}"


# @pytest.fixture
# def queue_data():
#     """Test queue data."""
#     return {
#         "queue_name": "test_queue",
#         "password": "test_password",
#         "metadata": {"test": "data"},
#     }
#
#
# @pytest.fixture
# def task_data(queue_data):
#     """Test task data."""
#     return {
#         "queue_name": queue_data["queue_name"],
#         "password": queue_data["password"],
#         "task_name": "test_task",
#         "args": {"param1": 1},
#         "metadata": {"test": "data"},
#     }
#
#
# @pytest.fixture
# def auth_headers(queue_data):
#     """Create Basic Auth headers."""
#     return get_auth_headers(queue_data["queue_name"], queue_data["password"])
#
#
# class TestQueueEndpoints:
#     """Test queue-related endpoints."""
#
#     def test_create_queue(self, test_app, queue_data):
#         response = test_app.post("/api/v1/queues", json=queue_data)
#         assert response.status_code == HTTP_200_OK
#         data = response.json()
#         assert data["status"] == "success"
#         assert "queue_id" in data
#
#     def test_get_queue(self, test_app, queue_data, auth_headers):
#         # Create queue first
#         response = test_app.post("/api/v1/queues", json=queue_data)
#         queue_id = response.json()["queue_id"]
#
#         response = test_app.get(
#             "/api/v1/queues",
#             headers=auth_headers,  # Use Basic Auth
#         )
#         assert response.status_code == HTTP_200_OK
#         data = response.json()
#         assert data["queue_id"] == queue_id
#         assert data["queue_name"] == queue_data["queue_name"]
#
#
# class TestTaskEndpoints:
#     """Test task-related endpoints."""
#
#     def test_submit_task(self, test_app, queue_data, task_data, auth_headers):
#         """Test task submission."""
#         # Create queue first
#         test_app.post("/api/v1/queues", json=queue_data)
#
#         response = test_app.post(
#             "/api/v1/tasks",
#             headers=auth_headers,  # Use Basic Auth
#             json={
#                 "task_name": task_data["task_name"],
#                 "args": task_data["args"],
#                 "metadata": task_data["metadata"],
#             },
#         )
#         assert response.status_code == HTTP_200_OK
#
#     def test_get_next_task(self, test_app, queue_data, task_data, auth_headers):
#         # Setup
#         test_app.post("/api/v1/queues", json=queue_data)
#         test_app.post("/api/v1/tasks", headers=auth_headers, json=task_data)
#
#         response = test_app.get(
#             "/api/v1/tasks/next",
#             headers=auth_headers,  # Use Basic Auth
#         )
#         assert response.status_code == HTTP_200_OK
#         data = response.json()
#         assert data["status"] in ["success", "no_task"]
#
#
# class TestWorkerEndpoints:
#     """Test worker-related endpoints."""
#
#     def test_create_worker(self, test_app, queue_data, auth_headers):
#         # Setup
#         test_app.post("/api/v1/queues", json=queue_data)
#
#         response = test_app.post(
#             "/api/v1/workers",
#             headers=auth_headers,  # Use Basic Auth
#             json={
#                 "worker_name": "test_worker",
#                 "metadata": {"test": "data"},
#             },
#         )
#         assert response.status_code == HTTP_200_OK
#
#     def test_worker_status_update(self, test_app, queue_data, auth_headers):
#         """Test worker status update endpoint."""
#         # Setup: Create queue and worker
#         test_app.post("/api/v1/queues", json=queue_data)
#
#         # Create worker with correct format
#         response = test_app.post(
#             "/api/v1/workers",
#             headers=auth_headers,
#             json={"worker_name": "test_worker", "metadata": {"test": "data"}},
#         )
#         assert response.status_code == HTTP_200_OK
#         data = response.json()
#         assert "worker_id" in data
#         worker_id = data["worker_id"]
#
#         # Test status updates
#         for status in ["suspended", "active"]:
#             # Update status
#             response = test_app.patch(
#                 f"/api/v1/workers/{worker_id}/status",
#                 headers=auth_headers,
#                 json={"status": status},
#             )
#             assert response.status_code == HTTP_200_OK
#             assert response.json()["status"] == "success"
#
#             # Verify worker status was updated
#             response = test_app.get(
#                 f"/api/v1/workers/{worker_id}", headers=auth_headers
#             )
#             assert response.status_code == HTTP_200_OK
#             data = response.json()
#             assert data["worker_id"] == worker_id
#             assert data["status"] == status
#             assert data["worker_name"] == "test_worker"
#             assert data["metadata"] == {"test": "data"}
#             assert "retries" in data
#             assert "created_at" in data
#             assert "last_modified" in data
