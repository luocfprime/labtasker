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
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from labtasker.api_models import (
    QueueCreateResponse,
    QueueGetResponse,
    Task,
    TaskFetchRequest,
    TaskFetchResponse,
    TaskLsRequest,
    TaskLsResponse,
    TaskStatusUpdateRequest,
    TaskSubmitRequest,
    TaskSubmitResponse,
    TaskUpdateRequest,
    Worker,
    WorkerCreateRequest,
    WorkerCreateResponse,
    WorkerLsRequest,
    WorkerLsResponse,
)
from labtasker.security import get_auth_headers
from labtasker.utils import get_current_time
from tests.fixtures.server import test_app

# Mark the entire file as integration and unit tests
pytestmark = [pytest.mark.integration, pytest.mark.unit]


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


def test_health(test_app):
    response = test_app.get("/health")
    assert response.status_code == HTTP_200_OK


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
        assert get_response.status_code == HTTP_401_UNAUTHORIZED

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
        response = test_app.post(
            "/api/v1/queues/me/tasks/search",
            headers=auth_headers,
            json=TaskLsRequest(offset=0, limit=5).model_dump(),
        )
        assert response.status_code == HTTP_200_OK, f"{response.json()}"
        assert "task_id" in response.json()["content"][0], f"{response.json()}"
        data = TaskLsResponse(**response.json())
        assert data.found is True
        assert len(data.content) == 5
        for i, task in enumerate(data.content):
            assert task.task_name == f"test_task_{i}"

        # get next 5
        response = test_app.post(
            "/api/v1/queues/me/tasks/search",
            headers=auth_headers,
            json=TaskLsRequest(offset=5, limit=5).model_dump(),
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
        response = test_app.post(
            "/api/v1/queues/me/tasks/search",
            headers=auth_headers,
            json=TaskLsRequest(task_name=task_submit_request.task_name).model_dump(),
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
            assert response.status_code == HTTP_204_NO_CONTENT, f"{response.json()}"

            # 4. Check heartbeat timestamp via ls
            response = test_app.post(
                "/api/v1/queues/me/tasks/search",
                headers=auth_headers,
                json=TaskLsRequest(
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

    def test_delete_task(
        self, test_app, setup_queue, auth_headers, task_submit_request
    ):
        # Submit a task first
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED

        task_id = response.json()["task_id"]

        # Now delete the task
        delete_response = test_app.delete(
            f"/api/v1/queues/me/tasks/{task_id}", headers=auth_headers
        )
        assert delete_response.status_code == HTTP_204_NO_CONTENT

        # Verify the task is deleted
        get_response = test_app.get(
            f"/api/v1/queues/me/tasks/{task_id}", headers=auth_headers
        )
        assert get_response.status_code == HTTP_404_NOT_FOUND

    def test_delete_non_existent_task(self, test_app, setup_queue, auth_headers):
        # Attempt to delete a non-existent task
        response = test_app.delete(
            "/api/v1/queues/me/tasks/non_existent_task_id", headers=auth_headers
        )
        assert response.status_code == HTTP_404_NOT_FOUND
        assert "Task not found" in response.json()["detail"]

    def test_get_task(self, test_app, setup_queue, auth_headers, task_submit_request):
        # Submit a task first
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED
        task_id = response.json()["task_id"]

        # Now get the task
        get_response = test_app.get(
            f"/api/v1/queues/me/tasks/{task_id}", headers=auth_headers
        )
        assert get_response.status_code == HTTP_200_OK
        task_data = Task(**get_response.json())
        assert task_data.task_id == task_id

    def test_get_non_existent_task(self, test_app, setup_queue, auth_headers):
        # Attempt to get a non-existent task
        response = test_app.get(
            "/api/v1/queues/me/tasks/non_existent_task_id", headers=auth_headers
        )
        assert response.status_code == HTTP_404_NOT_FOUND
        assert "Task not found" in response.json()["detail"]


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
        response = test_app.post(
            "/api/v1/queues/me/workers/search",
            headers=auth_headers,
            json=WorkerLsRequest(worker_id=worker_id).model_dump(),
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

    def test_get_worker(self, test_app, setup_queue, auth_headers):
        # Create a worker first
        worker_response = test_app.post(
            "/api/v1/queues/me/workers",
            headers=auth_headers,
            json=WorkerCreateRequest(
                worker_name="test_worker",
                max_retries=3,
                metadata={"tag": "test"},
            ).model_dump(),
        )
        assert worker_response.status_code == HTTP_201_CREATED
        worker_id = worker_response.json()["worker_id"]

        # Now get the worker
        get_response = test_app.get(
            f"/api/v1/queues/me/workers/{worker_id}", headers=auth_headers
        )
        assert get_response.status_code == HTTP_200_OK
        worker_data = Worker(**get_response.json())
        assert worker_data.worker_name == "test_worker"

    def test_get_non_existent_worker(self, test_app, setup_queue, auth_headers):
        # Attempt to get a non-existent worker
        response = test_app.get(
            "/api/v1/queues/me/workers/non_existent_worker_id", headers=auth_headers
        )
        assert response.status_code == HTTP_404_NOT_FOUND
        assert "Worker not found" in response.json()["detail"]


def test_report_task_status_with_unmatched_worker_id(
    test_app, setup_queue, auth_headers, task_submit_request
):
    # Submit a task first
    test_app.post(
        "/api/v1/queues/me/tasks",
        json=task_submit_request.model_dump(),
        headers=auth_headers,
    )

    # Create 2 workers
    worker_ids = []
    for i in range(2):
        worker_id = test_app.post(
            "/api/v1/queues/me/workers",
            headers=auth_headers,
            json=WorkerCreateRequest(
                worker_name="test_worker",
                max_retries=3,
                metadata={"test": "data"},
            ).model_dump(),
        ).json()["worker_id"]
        worker_ids.append(worker_id)

    # Fetch task using first worker
    response = test_app.post(
        "/api/v1/queues/me/tasks/next",
        headers=auth_headers,
        json=TaskFetchRequest(
            start_heartbeat=True,
            worker_id=worker_ids[0],
            extra_filter={"task_name": task_submit_request.task_name},
        ).model_dump(),
    )
    assert response.status_code == HTTP_200_OK, f"{response.json()}"

    task = TaskFetchResponse(**response.json()).task
    task_id = task.task_id

    # update status using second worker
    response = test_app.post(
        f"/api/v1/queues/me/tasks/{task_id}/status",
        headers=auth_headers,
        json=TaskStatusUpdateRequest(
            status="success", worker_id=worker_ids[1]
        ).model_dump(),
    )
    assert response.status_code == HTTP_409_CONFLICT, f"{response.json()}"

    # now update status using the correct matching first worker
    response = test_app.post(
        f"/api/v1/queues/me/tasks/{task_id}/status",
        headers=auth_headers,
        json=TaskStatusUpdateRequest(
            status="success", worker_id=worker_ids[0]
        ).model_dump(),
    )
    assert response.status_code == HTTP_200_OK, f"{response.json()}"


class TestUpdateTasks:

    def test_update_tasks_success(
        self, test_app, setup_queue, auth_headers, task_submit_request
    ):
        # Submit a task first
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED
        task_id = response.json()["task_id"]

        # Prepare update request
        update_request = [
            TaskUpdateRequest(_id=task_id, task_name="updated_task_name").model_dump(
                exclude_unset=True
            )
        ]

        # Update the task
        response = test_app.put(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            json=update_request,
        )
        assert response.status_code == HTTP_200_OK
        updated_tasks = TaskLsResponse(**response.json())
        assert updated_tasks.found is True
        assert updated_tasks.content[0].task_name == "updated_task_name"

    def test_update_tasks_invalid_id(self, test_app, setup_queue, auth_headers):
        # Prepare update request with an invalid task ID
        update_request = [
            TaskUpdateRequest(_id="invalid_task_id", task_name="new_name").model_dump(
                exclude_unset=True
            )
        ]

        # Attempt to update the task
        response = test_app.put(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            json=update_request,
        )
        assert response.status_code == HTTP_404_NOT_FOUND

    def test_update_tasks_no_changes(
        self, test_app, setup_queue, auth_headers, task_submit_request
    ):
        # Submit a task first
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED
        task_id = response.json()["task_id"]

        # Prepare update request with no changes
        update_request = [
            TaskUpdateRequest(_id=task_id).model_dump(exclude_unset=True)  # noqa
        ]

        # Update the task
        response = test_app.put(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            json=update_request,
        )
        assert response.status_code == HTTP_200_OK
        updated_tasks = TaskLsResponse(**response.json())
        assert updated_tasks.found is True
        assert (
            updated_tasks.content[0].task_id == task_id
        )  # Ensure the task ID remains the same

    def test_update_tasks_invalid_name(
        self, test_app, setup_queue, auth_headers, task_submit_request
    ):
        # Submit a task first
        response = test_app.post(
            "/api/v1/queues/me/tasks",
            json=task_submit_request.model_dump(),
            headers=auth_headers,
        )
        assert response.status_code == HTTP_201_CREATED
        task_id = response.json()["task_id"]

        # Prepare update request with an invalid name
        update_request = [{"task_id": task_id, "task_name": "#$@"}]  # Invalid name

        # Attempt to update the task
        response = test_app.put(
            "/api/v1/queues/me/tasks",
            headers=auth_headers,
            json=update_request,
        )
        assert response.status_code == HTTP_422_UNPROCESSABLE_ENTITY
