from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from labtasker.client import Client
from labtasker.errors import APIError, TransportError


def task_payload(task_id: str = "t_ABCDEFGHIJKL") -> dict[str, object]:
    return {
        "id": task_id,
        "queue": "default",
        "status": "pending",
        "name": None,
        "args": {},
        "metadata": {},
        "priority": 0,
        "attempt": 0,
        "max_attempts": 3,
        "routes": ["default"],
        "result": {},
        "last_error": None,
        "last_route": None,
        "created_at": "2026-08-20T12:00:00Z",
        "updated_at": "2026-08-20T12:00:00Z",
        "started_at": None,
        "finished_at": None,
    }


def mock_client(handler: Callable[[httpx.Request], httpx.Response], **kwargs: object) -> Client:
    client = Client(url="http://server.test/prefix", queue="default", **kwargs)
    client._http.close()
    client._http = httpx.Client(
        base_url="http://server.test/prefix/api/v2/",
        transport=httpx.MockTransport(handler),
    )
    return client


def error_response(status: int, code: str) -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"code": code, "message": "failed", "details": {}}},
    )


def test_submit_normalizes_body_and_preserves_id_across_transport_retry() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("offline", request=request)
        task_id = request.url.path.rsplit("/", 1)[-1]
        payload = task_payload(task_id)
        payload.update(json.loads(request.content))
        payload.update({"id": task_id, "status": "pending", "attempt": 0, "result": {}})
        return httpx.Response(201, json=payload)

    with mock_client(handler) as client:
        task = client.submit_task()
    assert len(requests) == 2
    assert requests[0].url == requests[1].url
    assert requests[0].content == requests[1].content
    assert task.id.startswith("t_") and len(task.id) == 14
    assert json.loads(requests[0].content) == {
        "name": None,
        "args": {},
        "metadata": {},
        "priority": 0,
        "max_attempts": 3,
        "routes": ["default"],
    }


def test_generated_id_collision_uses_a_new_id(monkeypatch: pytest.MonkeyPatch) -> None:
    generated = iter(["t_ABCDEFGHIJKL", "t_MNOPQRSTUVWX"])
    monkeypatch.setattr("labtasker.client._generate_task_id", lambda: next(generated))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        task_id = request.url.path.rsplit("/", 1)[-1]
        seen.append(task_id)
        if len(seen) == 1:
            return error_response(409, "task_id_conflict")
        return httpx.Response(201, json=task_payload(task_id))

    with mock_client(handler) as client:
        task = client.submit_task()
    assert seen == ["t_ABCDEFGHIJKL", "t_MNOPQRSTUVWX"]
    assert task.id == "t_MNOPQRSTUVWX"


def test_read_retries_database_busy_and_malformed_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labtasker.client._backoff", lambda _: None)
    responses = iter(
        [
            error_response(503, "database_busy"),
            httpx.Response(200, json={}),
            httpx.Response(200, json=task_payload()),
        ]
    )
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return next(responses)

    with mock_client(handler) as client:
        assert client.get_task("t_ABCDEFGHIJKL").id == "t_ABCDEFGHIJKL"
    assert calls == 3


def test_malformed_error_envelope_is_retryable_for_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("labtasker.client._backoff", lambda _: None)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(500, json={"detail": "wrong"})
        return httpx.Response(200, json=task_payload())

    with mock_client(handler) as client:
        assert client.get_task("t_ABCDEFGHIJKL").status == "pending"
    assert calls == 2


def test_valid_api_error_is_preserved_without_unapproved_retry() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            404,
            json={
                "error": {
                    "code": "task_not_found",
                    "message": "Task does not exist.",
                    "details": {"task_id": "t_ABCDEFGHIJKL"},
                }
            },
        )

    with mock_client(handler) as client, pytest.raises(APIError) as raised:
        client.get_task("t_ABCDEFGHIJKL")
    assert calls == 1
    assert raised.value.status_code == 404
    assert raised.value.code == "task_not_found"
    assert raised.value.details == {"task_id": "t_ABCDEFGHIJKL"}


def test_mutation_transport_failure_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("lost", request=request)

    with mock_client(handler) as client, pytest.raises(TransportError) as raised:
        client.cancel_task("t_ABCDEFGHIJKL")
    assert calls == 1
    assert raised.value.code == "transport_error"
    assert raised.value.details == {
        "operation": "cancel_task",
        "url": "http://server.test/prefix",
    }


def test_authorization_is_sent_but_never_exposed_by_client_error() -> None:
    authorization: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal authorization
        authorization = request.headers.get("Authorization")
        return httpx.Response(500, content=b"not-json")

    client = Client(url="http://server.test", token="super-secret", queue="default")
    client._http.close()
    client._http = httpx.Client(
        base_url="http://server.test/api/v2/",
        headers={"Authorization": "Bearer super-secret"},
        transport=httpx.MockTransport(handler),
    )
    with client, pytest.raises(TransportError) as raised:
        client.create_queue("new")
    assert authorization == "Bearer super-secret"
    assert "super-secret" not in str(raised.value.as_envelope())


def test_close_is_idempotent_and_closed_client_never_reopens() -> None:
    client = mock_client(lambda _: httpx.Response(200, json=[]))
    client.close()
    client.close()
    with pytest.raises(RuntimeError, match=r"^Client is closed\.$"):
        client.get_task("not-even-validated")


def test_configuration_is_snapshotted_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LABTASKER_QUEUE", "first")
    client = Client(url="http://server.test")
    monkeypatch.setenv("LABTASKER_QUEUE", "second")
    try:
        assert client.configuration.queue == "first"
    finally:
        client.close()


def test_claim_replays_same_run_id_and_parses_empty_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("labtasker.client._backoff", lambda _: None)
    requests: list[httpx.Request] = []

    def claimed_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ConnectError("response lost", request=request)
        payload = task_payload()
        payload.update({"status": "running", "attempt": 1, "last_route": "gpu"})
        return httpx.Response(
            200,
            json={
                "task": payload,
                "run_id": "r_ABCDEFGHIJKL",
                "lease_expires_at": "2026-08-20T12:05:00Z",
            },
        )

    with mock_client(claimed_handler) as client:
        claim = client._claim(route="gpu", run_id="r_ABCDEFGHIJKL")
    assert claim is not None
    assert claim.task.status == "running"
    assert claim.task.attempt == 1
    assert [json.loads(request.content) for request in requests] == [
        {"route": "gpu", "run_id": "r_ABCDEFGHIJKL"},
        {"route": "gpu", "run_id": "r_ABCDEFGHIJKL"},
    ]

    with mock_client(lambda _: httpx.Response(204)) as client:
        assert client._claim(route="gpu", run_id="r_MNOPQRSTUVWX") is None


def test_worker_protocol_actions_are_one_shot_and_strict() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"lease_expires_at": "2026-08-20T12:05:00Z"})
        return httpx.Response(204)

    with mock_client(handler) as client:
        heartbeat = client._heartbeat(
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
        )
        assert heartbeat.lease_expires_at.isoformat() == "2026-08-20T12:05:00+00:00"
        client._complete(
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
            result={"score": 0.5},
        )
        client._fail(
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
            error_type="ValueError",
            message="bad value",
            traceback=None,
        )
        client._unclaim(task_id="t_ABCDEFGHIJKL", run_id="r_ABCDEFGHIJKL")

    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "heartbeat",
        "complete",
        "fail",
        "unclaim",
    ]
    assert [json.loads(request.content) for request in requests] == [
        {"run_id": "r_ABCDEFGHIJKL"},
        {"run_id": "r_ABCDEFGHIJKL", "result": {"score": 0.5}},
        {
            "run_id": "r_ABCDEFGHIJKL",
            "error": {"type": "ValueError", "message": "bad value", "traceback": None},
        },
        {"run_id": "r_ABCDEFGHIJKL"},
    ]


def test_worker_terminal_action_transport_failure_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("lost", request=request)

    with mock_client(handler) as client, pytest.raises(TransportError):
        client._complete(
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
            result={},
        )
    assert calls == 1
