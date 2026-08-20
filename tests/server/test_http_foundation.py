from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Scope

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings
from labtasker_server.middleware import RequestBodyLimitMiddleware
from labtasker_server.validation import MAX_TASK_DATA_BYTES


def test_health_and_schema_discovery_are_unauthenticated(client: TestClient) -> None:
    assert client.get("/health").json() == {
        "status": "ok",
        "api_version": "2",
        "database": "ok",
    }
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert "/api/v2/queues" in schema.json()["paths"]
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_openapi_describes_the_complete_v2_surface_and_real_response_statuses(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    expected_methods = {
        "/health": {"get"},
        "/api/v2/queues": {"get"},
        "/api/v2/queues/{queue}": {"put", "delete"},
        "/api/v2/queues/{queue}/tasks": {"get", "patch"},
        "/api/v2/queues/{queue}/tasks/count": {"get"},
        "/api/v2/queues/{queue}/tasks/claim": {"post"},
        "/api/v2/queues/{queue}/tasks/{task_id}": {"put", "get", "patch", "delete"},
        "/api/v2/queues/{queue}/tasks/{task_id}/heartbeat": {"post"},
        "/api/v2/queues/{queue}/tasks/{task_id}/complete": {"post"},
        "/api/v2/queues/{queue}/tasks/{task_id}/fail": {"post"},
        "/api/v2/queues/{queue}/tasks/{task_id}/unclaim": {"post"},
        "/api/v2/queues/{queue}/tasks/{task_id}/cancel": {"post"},
        "/api/v2/queues/{queue}/tasks/{task_id}/requeue": {"post"},
    }
    assert {path: set(methods) for path, methods in schema["paths"].items()} == expected_methods

    queue_create = schema["paths"]["/api/v2/queues/{queue}"]["put"]
    task_create = schema["paths"]["/api/v2/queues/{queue}/tasks/{task_id}"]["put"]
    claim = schema["paths"]["/api/v2/queues/{queue}/tasks/claim"]["post"]
    assert {"200", "201"} <= set(queue_create["responses"])
    assert {"200", "201"} <= set(task_create["responses"])
    assert {"200", "204"} <= set(claim["responses"])

    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v2"):
            continue
        for operation in methods.values():
            assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
                "$ref": "#/components/schemas/ErrorEnvelope"
            }
            assert operation["security"] == [{"HTTPBearer": []}]

    health = schema["paths"]["/health"]["get"]
    assert health["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HealthyResponse"
    }
    assert health["responses"]["503"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UnhealthyResponse"
    }
    assert "security" not in health


def test_health_database_failure_is_sanitized(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def broken_session() -> Iterator[None]:
        raise OSError("secret database path /private/server.db")
        yield  # pragma: no cover

    monkeypatch.setattr(client.app.state.database, "read_session", broken_session)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "api_version": "2",
        "database": "error",
    }
    assert "private" not in response.text


def test_application_endpoints_require_configured_bearer_token(tmp_path: Path) -> None:
    app = create_app(ServerSettings(database=tmp_path / "server.db", token="secret"))
    with TestClient(app) as client:
        for authorization in (None, "Basic secret", "Bearer wrong", "Bearer"):
            headers = {} if authorization is None else {"Authorization": authorization}
            response = client.get("/api/v2/queues", headers=headers)
            assert response.status_code == 401
            assert response.headers["www-authenticate"] == "Bearer"
            assert response.json()["error"]["code"] == "unauthorized"

        assert (
            client.get(
                "/api/v2/queues",
                headers={"Authorization": "Bearer secret"},
            ).status_code
            == 200
        )
        assert client.get("/health").status_code == 200
        assert client.get("/openapi.json").status_code == 200


def test_unknown_request_fields_use_stable_validation_envelope(client: TestClient) -> None:
    response = client.put(
        "/api/v2/queues/default/tasks/t_ABCDEFGHIJKL",
        json={"unexpected": True},
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_task",
            "message": "Request validation failed.",
            "details": {
                "errors": [
                    {
                        "location": ["body", "unexpected"],
                        "message": "Extra inputs are not permitted",
                    }
                ]
            },
        }
    }


def test_malformed_json_has_one_stable_body_location(client: TestClient) -> None:
    response = client.put(
        "/api/v2/queues/default/tasks/t_ABCDEFGHIJKL",
        content=b'{"args":',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request validation failed.",
            "details": {
                "errors": [
                    {"location": ["body"], "message": "Malformed JSON body."},
                ]
            },
        }
    }


def test_declared_oversized_request_is_rejected(client: TestClient) -> None:
    body = b"x" * (MAX_TASK_DATA_BYTES + 1)
    response = client.put(
        "/api/v2/queues/default/tasks/t_ABCDEFGHIJKL",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {
        "error": {
            "code": "request_too_large",
            "message": "Request body exceeds the 1 MiB limit.",
            "details": {"max_bytes": MAX_TASK_DATA_BYTES},
        }
    }


def test_streamed_oversized_request_is_stopped_without_content_length() -> None:
    downstream_called = False

    async def downstream(scope: Scope, receive: object, send: object) -> None:
        nonlocal downstream_called
        downstream_called = True

    middleware = RequestBodyLimitMiddleware(downstream, max_bytes=4)
    incoming: list[Message] = [
        {"type": "http.request", "body": b"123", "more_body": True},
        {"type": "http.request", "body": b"45", "more_body": False},
    ]
    outgoing: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0)

    async def send(message: Message) -> None:
        outgoing.append(message)

    scope = cast(
        Scope,
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
            "root_path": "",
        },
    )
    asyncio.run(middleware(scope, receive, send))

    assert downstream_called is False
    assert outgoing[0] == {
        "type": "http.response.start",
        "status": 413,
        "headers": outgoing[0]["headers"],
    }
