from datetime import timedelta

import pytest
from freezegun import freeze_time
from pydantic import SecretStr, ValidationError
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from labtasker.api_models import (
    QueueCreateResponse,
    QueueGetResponse,
    TaskFetchRequest,
    TaskFetchResponse,
    TaskLsRequest,
    TaskLsResponse,
    TaskStatusUpdateRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
    WorkerCreateRequest,
    WorkerCreateResponse,
    WorkerLsRequest,
    WorkerLsResponse,
)
from labtasker.security import get_auth_headers
from labtasker.utils import get_current_time
from tests.fixtures.server import test_app


@pytest.fixture
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
def test_health(test_app):
    response = test_app.get("/health")
    assert response.status_code == HTTP_200_OK


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

    def test_update_queue_name(self, test_app, setup_queue, queue_create_request):
        auth_headers = get_auth_headers(
            setup_queue.queue_id, queue_create_request.password
        )  # use queue_id for authentication since queue_name is about to be changed
        new_name = "updated_queue_name"
        response = test_app.put(
            "/api/v1/queues/me",
            headers=auth_headers,
            json={"new_queue_name": new_name},
        )
        assert response.status_code == HTTP_200_OK

        # Verify the update
        response = test_app.get("/api/v1/queues/me", headers=auth_headers)
        assert response.status_code == HTTP_200_OK
        data = QueueGetResponse(**response.json())
        assert data.queue_name == new_name

    def test_update_queue_password(self, test_app, setup_queue, auth_headers):
        new_password = "new_password"
        response = test_app.put(
            "/api/v1/queues/me",
            headers=auth_headers,
            json={"new_password": new_password},
        )
        assert response.status_code == HTTP_200_OK

        # Verify the update by attempting to access with the new password
        new_auth_headers = get_auth_headers(
            setup_queue.queue_id, SecretStr(new_password)
        )
        response = test_app.get("/api/v1/queues/me", headers=new_auth_headers)
        assert response.status_code == HTTP_200_OK

    def test_update_queue_metadata(self, test_app, setup_queue, auth_headers):
        new_metadata = {"key": "value"}
        response = test_app.put(
            "/api/v1/queues/me",
            headers=auth_headers,
            json={"metadata_update": new_metadata},
        )
        assert response.status_code == HTTP_200_OK

        # Verify the update
        response = test_app.get("/api/v1/queues/me", headers=auth_headers)
        assert response.status_code == HTTP_200_OK
        data = QueueGetResponse(**response.json())

        for k, v in new_metadata.items():
            assert data.metadata[k] == v, f"{k} not found in metadata"

    def test_update_queue_no_changes(
        self, test_app, setup_queue, queue_create_request, auth_headers
    ):
        response = test_app.put(
            "/api/v1/queues/me",
            headers=auth_headers,
            json={},
        )
        assert response.status_code == HTTP_200_OK
        data = QueueGetResponse(**response.json())
        assert data.queue_name == queue_create_request.queue_name
        assert data.metadata == queue_create_request.metadata

    def test_update_queue_invalid_name(self, test_app, setup_queue, auth_headers):
        # Attempt to update with an invalid name (e.g., empty string)
        response = test_app.put(
            "/api/v1/queues/me",
            headers=auth_headers,
            json={"new_queue_name": "#$@"},  # invalid name
        )
        assert response.status_code == HTTP_422_UNPROCESSABLE_ENTITY


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
        data = TaskLsResponse(**response.json())
        assert data.found is True
        assert len(data.content) == 5
        for i, task in enumerate(data.content):
            assert task.task_name == f"test_task_{i}"

        # get next 5
        response = test_app.get(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            params=TaskLsRequest(offset=5, limit=5).model_dump(),
        )
        assert response.status_code == HTTP_200_OK, f"{response.json()}"
        data = TaskLsResponse(**response.json())
        assert data.found is True
        assert len(data.content) == 5
        for i, task in enumerate(data.content):
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
        data = TaskLsResponse(**response.json())
        assert data.found is True
        assert data.content[0].status == "success"

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

        start = get_current_time()

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
            data = TaskLsResponse(**response.json())
            assert data.content[0].last_heartbeat is not None
            assert (
                abs(
                    data.content[0].last_heartbeat.timestamp()
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
        assert worker_ls.content[0].status == "crashed"

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
