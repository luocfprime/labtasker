from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from labtasker.client import Client
from labtasker.errors import APIError, TransportError
from labtasker.validation import RequestValidationError


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


@pytest.mark.parametrize("status", [200, 503])
@pytest.mark.parametrize("recovers", [False, True])
def test_deep_json_responses_keep_bounded_transport_retries(
    monkeypatch: pytest.MonkeyPatch, status: int, recovers: bool
) -> None:
    monkeypatch.setattr("labtasker.client.RETRY_BACKOFF_SECONDS", (0.0, 0.0))
    nested = b"[" * 1100 + b"0" + b"]" * 1100
    body = nested if status == 200 else b'{"error":' + nested + b"}"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if recovers and len(requests) == 3:
            return httpx.Response(200, json=[])
        return httpx.Response(status, content=body)

    with mock_client(handler) as client:
        if recovers:
            assert client.list_queues() == []
        else:
            with pytest.raises(TransportError):
                client.list_queues()
    assert len(requests) == 3


@pytest.mark.parametrize(
    ("version", "expected", "warn"),
    [
        ("2.1.0", "2.1.0", True),
        ("2.10.0", "2.10.0", False),
        ("3.0.0", "3.0.0", False),
        ("2.10.0rc1", "2.10.0rc1", True),
        (None, None, False),
        ("unknown", None, False),
        ("9" * 129, None, False),
    ],
)
def test_version_warning_uses_business_response_only(
    version: str | None,
    expected: str | None,
    warn: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("labtasker.__version__", "2.10.0")
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        headers = {} if version is None else {"Labtasker-Server-Version": version}
        return httpx.Response(200, json=[], headers=headers)

    with mock_client(handler) as client:
        assert client.server_version is None
        assert requests == []
        assert client.list_queues() == []
        assert client.list_queues() == []
        assert client.server_version == expected
    assert len(requests) == 2
    assert all(request.url.path.endswith("/api/v2/queues") for request in requests)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("warning:") == int(warn)
    if warn:
        assert "Consider upgrading the Server to 2.10.0 or later" in captured.err


def test_version_updates_and_missing_header_clear_previous_observation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    versions = iter(["0.1.0", "0.2.0", None, "invalid", "0.1.0"])

    def handler(_: httpx.Request) -> httpx.Response:
        version = next(versions)
        return httpx.Response(
            200, json=[], headers={} if version is None else {"Labtasker-Server-Version": version}
        )

    with mock_client(handler) as client:
        for expected in ["0.1.0", "0.2.0", None, None, "0.1.0"]:
            client.list_queues()
            assert client.server_version == expected
    assert capsys.readouterr().err.count("warning:") == 2


def test_version_warning_preserves_api_error_and_request_count(
    capsys: pytest.CaptureFixture[str],
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = error_response(409, "task_not_running")
        response.headers["Labtasker-Server-Version"] = "0.1.0"
        return response

    with mock_client(handler) as client, pytest.raises(APIError) as raised:
        client.cancel_task("t_ABCDEFGHIJKL")
    assert len(requests) == 1
    assert raised.value.status_code == 409
    assert raised.value.code == "task_not_running"
    assert raised.value.message == "failed"
    assert raised.value.details == {}
    assert capsys.readouterr().err.count("warning:") == 1


def test_http_endpoint_is_announced_once_after_connection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with mock_client(lambda _: httpx.Response(200, json=[{"name": "default"}])) as client:
        assert [queue.name for queue in client.list_queues()] == ["default"]
        assert [queue.name for queue in client.list_queues()] == ["default"]

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "[labtasker] connected server=remote transport=http url=http://server.test/prefix\n"
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
        client._report_progress(
            task_id="t_ABCDEFGHIJKL",
            run_id="r_ABCDEFGHIJKL",
            progress={"step": 3, "loss": 0.5},
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
        "progress",
        "fail",
        "unclaim",
    ]
    assert [json.loads(request.content) for request in requests] == [
        {"run_id": "r_ABCDEFGHIJKL"},
        {"run_id": "r_ABCDEFGHIJKL", "result": {"score": 0.5}},
        {"run_id": "r_ABCDEFGHIJKL", "progress": {"step": 3, "loss": 0.5}},
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


def test_worker_health_uses_unversioned_endpoint_and_strict_v2_shape() -> None:
    requests: list[httpx.Request] = []

    def healthy(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"status": "ok", "api_version": "2", "database": "ok"},
        )

    with mock_client(healthy) as client:
        health = client._health()
    assert health.api_version == "2"
    assert requests[0].url == "http://server.test/prefix/health"

    with (
        mock_client(
            lambda _: httpx.Response(
                200,
                json={"status": "ok", "api_version": "3", "database": "ok"},
            )
        ) as client,
        pytest.raises(TransportError),
    ):
        client._health()


@pytest.mark.parametrize("filter_value", ["", "   ", "\ud800"])
def test_invalid_filter_fails_locally_before_network(filter_value: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    with mock_client(handler) as client, pytest.raises(RequestValidationError):
        client.list_tasks(filter=filter_value)
    assert calls == 0


@pytest.mark.parametrize("value", ["\ud800", "\udfff"])
@pytest.mark.parametrize(
    ("operation", "field", "options"),
    [
        ("list_tasks", "name", {}),
        ("count_tasks", "name", {}),
        ("count_tasks", "name", {"group_by": ["routes"]}),
        ("list_tasks", "cursor", {}),
        ("count_tasks", "cursor", {"group_by": ["routes"]}),
        ("list_workers", "cursor", {}),
        ("count_workers", "cursor", {"group_by": ["route"]}),
    ],
)
def test_query_surrogates_fail_before_local_endpoint_preparation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    operation: str,
    field: str,
    options: dict[str, object],
    value: str,
) -> None:
    def unexpected_prepare() -> None:
        pytest.fail("Invalid query must not prepare or start the local Server")

    with Client._from_local_directory(tmp_path, queue="default") as client:
        monkeypatch.setattr(client, "_prepare_endpoint", unexpected_prepare)
        with pytest.raises(RequestValidationError, match=field):
            getattr(client, operation)(**options, **{field: value})
    assert not (tmp_path / ".labtasker").exists()


@pytest.mark.parametrize("operation", ["list_tasks", "count_tasks"])
def test_query_names_keep_selector_rules(operation: str) -> None:
    name = "😀\0" * 300

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name"] == name
        body = {"count": 0} if operation == "count_tasks" else {"items": [], "next_cursor": None}
        return httpx.Response(200, json=body)

    with mock_client(handler) as client:
        getattr(client, operation)(name=name)


@pytest.mark.parametrize("operation", ["list_tasks", "count_tasks"])
def test_name_fuzzy_is_forwarded_with_exact_and_other_selectors(operation: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["name_fuzzy"] == " EV tr "
        assert request.url.params["name"] == "train_eval"
        assert request.url.params["status"] == "pending"
        assert request.url.params["filter"] == "priority > 0"
        body = {"count": 0} if operation == "count_tasks" else {"items": [], "next_cursor": None}
        return httpx.Response(200, json=body)

    with mock_client(handler) as client:
        getattr(client, operation)(
            name="train_eval", name_fuzzy=" EV tr ", status="pending", filter="priority > 0"
        )
        with pytest.raises(RequestValidationError, match="name_fuzzy"):
            getattr(client, operation)(name_fuzzy=42)
        with pytest.raises(RequestValidationError, match="name_fuzzy"):
            getattr(client, operation)(name_fuzzy="\ud800")
