from __future__ import annotations

import json
import threading
import time

import httpx
import pytest
from typer.testing import CliRunner

from labtasker import Client, GroupCountPage
from labtasker.cli import app
from labtasker.config import ResolvedConfig
from labtasker.errors import TransportError
from labtasker.observations import ObservationReporter
from labtasker.validation import RequestValidationError


def make_client(handler: object) -> Client:
    client = Client(url="http://server", queue="default")
    client._http.close()
    client._http = httpx.Client(
        base_url="http://server/api/v2/", transport=httpx.MockTransport(handler)
    )
    return client


def test_grouped_count_preserves_scalar_and_serializes_sequence() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        fields = request.url.params.get("group_by")
        return httpx.Response(
            200,
            json={"count": 2}
            if fields is None
            else {
                "group_by": fields.split(","),
                "count": 2,
                "items": [{"key": {"routes": "a", "status": "pending"}, "count": 2}],
                "next_cursor": None,
            },
        )

    with make_client(handler) as client:
        assert client.count_tasks(status="pending") == 2
        page = client.count_tasks(group_by=("routes", "status"), limit=1)
        assert isinstance(page, GroupCountPage)
        assert page.items[0].count == 2
        assert dict(requests[0].url.params) == {"status": "pending"}
        assert requests[1].url.params["group_by"] == "routes,status"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"group_by": "routes,status"},
        {"group_by": []},
        {"group_by": ["routes", "routes"]},
        {"group_by": ["routes", " status"]},
        {"group_by": ["last_route"]},
        {"limit": 100},
        {"cursor": "x"},
        {"group_by": ["routes"], "limit": True},
    ],
)
def test_invalid_grouping_fails_before_request(kwargs: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid input reached network")

    with make_client(handler) as client, pytest.raises(RequestValidationError):
        client.count_tasks(**kwargs)


@pytest.mark.parametrize("field", ["metadata.node", "telemetry.gpu"])
def test_dynamic_worker_fields_cannot_be_grouped(field: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid input reached network")

    with make_client(handler) as client, pytest.raises(RequestValidationError):
        client.count_workers(group_by=[field])


def test_old_server_scalar_does_not_masquerade_as_grouped_result() -> None:
    with (
        make_client(lambda request: httpx.Response(200, json={"count": 4})) as client,
        pytest.raises(TransportError, match=r"does not support.*grouped-count"),
    ):
        client.count_tasks(group_by=["status"])


@pytest.mark.parametrize(
    "args",
    [
        ["--group-by", "routes, status"],
        ["--group-by", "routes", "--group-by", "status"],
        ["--group-by", ""],
        ["--group-by", "routes,routes"],
        ["--limit", "100"],
    ],
)
def test_cli_count_rejects_malformed_grouping_before_client(
    monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    def unexpected(**kwargs: object) -> None:
        pytest.fail("invalid CLI parameters constructed a Client")

    monkeypatch.setattr("labtasker.cli.Client", unexpected)
    result = CliRunner().invoke(app, ["task", "count", *args])
    assert result.exit_code == 2


def test_cli_grouped_json_and_help(monkeypatch: pytest.MonkeyPatch) -> None:
    page = GroupCountPage(
        group_by=["route", "status"],
        count=1,
        items=[{"key": {"route": "a", "status": "idle"}, "count": 1}],
        next_cursor=None,
    )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def count_workers(self, **kwargs):
            assert kwargs["group_by"] == ["route", "status"]
            return page

    monkeypatch.setattr("labtasker.cli.Client", FakeClient)
    runner = CliRunner()
    result = runner.invoke(app, ["worker", "count", "--group-by", "route,status"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == page.model_dump(mode="json")
    for resource in ["task", "worker"]:
        help_text = runner.invoke(app, [resource, "count", "--help"]).stdout
        assert "Comma-separated" in help_text
        assert "no spaces" in " ".join(help_text.split())


def test_reporter_coalesces_and_shutdown_never_waits_for_blocked_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            entered.set()
            assert release.wait(3)
        return httpx.Response(204)

    monkeypatch.setattr(
        "labtasker.observations._make_http_client",
        lambda config: httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(handler)
        ),
    )
    monkeypatch.setattr("labtasker.observations.SHUTDOWN_WAIT_SECONDS", 0.05)
    config = ResolvedConfig(url="http://server", queue="default", token=None, local=None)
    reporter = ObservationReporter(config, "a")
    reporter.__enter__()
    try:
        assert entered.wait(2)
        reporter.activity("t_ABCDEFGHIJKL")
        reporter.activity(None)
        reporter.activity("t_BCDEFGHIJKLM")
        before = time.monotonic()
        reporter.__exit__(None, None, None)
        assert time.monotonic() - before < 0.5
        assert len(requests) == 1
    finally:
        release.set()
        reporter._thread.join(2)
    assert not reporter._thread.is_alive()
    assert len(requests) == 1  # shutdown budget elapsed; no new requests


def test_reporter_sends_latest_busy_then_idle_and_withdraws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    busy = threading.Event()
    idle = threading.Event()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            data = json.loads(request.content)
            (busy if data["status"] == "busy" else idle).set()
        return httpx.Response(204)

    monkeypatch.setattr(
        "labtasker.observations._make_http_client",
        lambda config: httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(handler)
        ),
    )
    config = ResolvedConfig(url="http://server", queue="default", token=None, local=None)
    with ObservationReporter(config, "a") as reporter:
        assert idle.wait(2)
        reporter.activity("t_ABCDEFGHIJKL")
        assert busy.wait(2)
        idle.clear()
        reporter.activity(None)
        assert idle.wait(2)
    assert requests[-1].method == "DELETE"
    assert len({request.url.path for request in requests}) == 1
    assert ObservationReporter(config, "a").id != reporter.id


def test_reporter_keeps_invocation_metadata_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reported = threading.Event()
    payloads: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            payloads.append(json.loads(request.content))
            reported.set()
        return httpx.Response(204)

    monkeypatch.setattr(
        "labtasker.observations._make_http_client",
        lambda config: httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(handler)
        ),
    )
    metadata = {"node": {"name": "node-7"}}
    config = ResolvedConfig(url="http://server", queue="default", token=None, local=None)
    with ObservationReporter(config, "a", metadata) as reporter:
        assert reported.wait(2)
        metadata["node"] = {"name": "changed"}
        reported.clear()
        reporter.activity("t_ABCDEFGHIJKL")
        assert reported.wait(2)
    assert payloads[-1]["metadata"] == {"node": {"name": "node-7"}}


def test_periodic_report_repairs_failure_without_activity_change(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repaired = threading.Event()
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            attempts.append(json.loads(request.content))
            if len(attempts) == 1:
                raise httpx.ConnectError("offline", request=request)
            repaired.set()
        return httpx.Response(204)

    monkeypatch.setattr("labtasker.observations.REPORT_INTERVAL_SECONDS", 0.02)
    monkeypatch.setattr(
        "labtasker.observations._make_http_client",
        lambda config: httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(handler)
        ),
    )
    caplog.set_level("INFO", logger="labtasker.worker")
    config = ResolvedConfig(url="http://server", queue="default", token=None, local=None)
    with ObservationReporter(config, "a"):
        assert repaired.wait(2)
    assert len(attempts) >= 2
    assert all(
        item == {"route": "a", "status": "idle", "task_id": None, "metadata": {}}
        for item in attempts
    )
    assert "reporting recovered" in caplog.text


@pytest.mark.parametrize("exit_during_initialization", [False, True])
def test_slow_transport_initialization_respects_latest_activity_and_shutdown(
    monkeypatch: pytest.MonkeyPatch, exit_during_initialization: bool
) -> None:
    initializing = threading.Event()
    release = threading.Event()
    reported = threading.Event()
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        reported.set()
        return httpx.Response(204)

    def make_transport(config: ResolvedConfig) -> httpx.Client:
        initializing.set()
        assert release.wait(3)
        return httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(handler)
        )

    monkeypatch.setattr("labtasker.observations._make_http_client", make_transport)
    monkeypatch.setattr("labtasker.observations.SHUTDOWN_WAIT_SECONDS", 0.02)
    config = ResolvedConfig(url="http://server", queue="default", token=None, local=None)
    reporter = ObservationReporter(config, "a")
    reporter.__enter__()
    try:
        assert initializing.wait(2)
        reporter.activity("t_ABCDEFGHIJKL")
        if exit_during_initialization:
            reporter.__exit__(None, None, None)
            release.set()
            reporter._thread.join(2)
            assert not reporter._thread.is_alive()
            assert requests == []
        else:
            release.set()
            assert reported.wait(2)
            assert json.loads(requests[0].content) == {
                "route": "a",
                "status": "busy",
                "task_id": "t_ABCDEFGHIJKL",
                "metadata": {},
            }
    finally:
        release.set()
        if not exit_during_initialization:
            reporter.__exit__(None, None, None)
        reporter._thread.join(2)


def test_blocked_withdrawal_does_not_delay_exit_or_replace_original_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered = threading.Event()
    withdrawing = threading.Event()
    release = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PUT":
            registered.set()
        else:
            withdrawing.set()
            assert release.wait(3)
            raise httpx.ReadTimeout("withdrawal unavailable", request=request)
        return httpx.Response(204)

    monkeypatch.setattr(
        "labtasker.observations._make_http_client",
        lambda config: httpx.Client(
            base_url="http://server/api/v2/", transport=httpx.MockTransport(handler)
        ),
    )
    monkeypatch.setattr("labtasker.observations.SHUTDOWN_WAIT_SECONDS", 0.05)
    config = ResolvedConfig(url="http://server", queue="default", token=None, local=None)
    reporter = ObservationReporter(config, "a")
    try:
        with pytest.raises(RuntimeError, match="original exit"), reporter:
            assert registered.wait(2)
            before = time.monotonic()
            raise RuntimeError("original exit")
        assert withdrawing.is_set()
        assert time.monotonic() - before < 0.5
    finally:
        release.set()
        reporter._thread.join(2)
    assert not reporter._thread.is_alive()
