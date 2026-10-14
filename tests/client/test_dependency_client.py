from __future__ import annotations

import json

import httpx
import pytest
from test_client import mock_client, task_payload

from labtasker.models import Task, TaskInfo
from labtasker.validation import RequestValidationError

A = "t_ABCDEFGHIJKL"
B = "t_MNOPQRSTUVWX"


def test_client_preserves_dependency_lists_on_create_read_and_update() -> None:
    dependencies = [B, A, B]

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["dependencies"] == dependencies
        return httpx.Response(
            201 if request.method == "PUT" else 200,
            json={**task_payload(), "dependencies": dependencies},
        )

    with mock_client(handler) as client:
        task = client.submit_task(dependencies=dependencies)
        assert task.dependencies == dependencies
        assert (
            client.update_task(task.id, {"dependencies": dependencies}).dependencies == dependencies
        )
    assert Task.model_validate_json(json.dumps(task_payload())).dependencies == []
    assert "dependencies" in TaskInfo.model_fields


@pytest.mark.parametrize("value", ["bad", {}, [1], [True], ["bad"], (A,), [[A]]])
def test_client_rejects_malformed_dependencies_before_network(value: object) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid dependencies must not reach the Server")

    with mock_client(handler) as client:
        with pytest.raises(RequestValidationError):
            client.submit_task(dependencies=value)
        with pytest.raises(RequestValidationError):
            client.update_task(A, {"dependencies": value})
