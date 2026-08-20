from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

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
