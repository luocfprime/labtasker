from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from labtasker.client import Client
from labtasker.errors import APIError, TransportError
from labtasker.models import ClaimResponse, Task
from labtasker.worker import _claim_backoff_delay, _next_claim

UTC = timezone.utc


def make_claim(
    *,
    task_id: str = "t_ABCDEFGHIJKL",
    run_id: str = "r_ABCDEFGHIJKL",
) -> ClaimResponse:
    task = Task.model_validate(
        {
            "id": task_id,
            "queue": "default",
            "status": "running",
            "name": "claim-test",
            "args": {},
            "metadata": {},
            "priority": 0,
            "attempt": 1,
            "max_attempts": 3,
            "routes": ["default"],
            "result": {},
            "last_error": None,
            "last_route": "default",
            "created_at": datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
            "started_at": datetime(2026, 8, 20, 12, 1, tzinfo=UTC),
            "finished_at": None,
        },
        strict=True,
    )
    return ClaimResponse(
        task=task,
        run_id=run_id,
        lease_expires_at=datetime(2026, 8, 20, 12, 6, tzinfo=UTC),
    )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def elapse(self, seconds: float) -> None:
        self.now += seconds


class ScriptedClient:
    def __init__(
        self,
        claims: list[object],
        *,
        heartbeats: list[object] | None = None,
        repair: Any = None,
    ) -> None:
        self.claims = deque(claims)
        self.heartbeats = deque([] if heartbeats is None else heartbeats)
        self.repair = repair
        self.claim_calls: list[tuple[str, str, str]] = []
        self.heartbeat_calls: list[tuple[str, str, str, bool]] = []
        self.repair_calls: list[TransportError] = []

    def _claim(self, *, route: str, run_id: str, queue: str) -> ClaimResponse | None:
        self.claim_calls.append((queue, route, run_id))
        return _resolve(self.claims.popleft())

    def _heartbeat(
        self,
        *,
        task_id: str,
        run_id: str,
        queue: str,
        recover_local_connect: bool,
    ) -> object:
        self.heartbeat_calls.append((queue, task_id, run_id, recover_local_connect))
        return _resolve(self.heartbeats.popleft())

    def _repair_local_connection(self, error: TransportError) -> None:
        self.repair_calls.append(error)
        if self.repair is not None:
            _resolve(self.repair)


def _resolve(value: object) -> Any:
    if isinstance(value, BaseException):
        raise value
    if callable(value):
        return value()
    return value


def install_clock(monkeypatch: pytest.MonkeyPatch, clock: FakeClock) -> None:
    monkeypatch.setattr("labtasker.worker.time.monotonic", clock.monotonic)
    monkeypatch.setattr("labtasker.worker.time.sleep", clock.sleep)
    monkeypatch.setattr(
        "labtasker.worker._claim_backoff_delay",
        lambda index: (1.0, 2.0, 4.0, 8.0, 10.0)[min(index, 4)],
    )
    run_ids = iter(
        [
            "r_ABCDEFGHIJKL",
            "r_MNOPQRSTUVWX",
            "r_ZYXWVUTSRQPO",
            "r_BCDEFGHIJKLM",
        ]
    )
    monkeypatch.setattr("labtasker.worker._generate_run_id", lambda: next(run_ids))


def test_empty_claims_back_off_and_confirm_idle_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    client = ScriptedClient([None, None, None])

    assert _next_claim(client, route="default", queue="default", idle_timeout=3) is None

    assert clock.sleeps == [1.0, 2.0]
    assert [call[2] for call in client.claim_calls] == [
        "r_ABCDEFGHIJKL",
        "r_MNOPQRSTUVWX",
        "r_ZYXWVUTSRQPO",
    ]


def test_claim_outage_reuses_run_id_and_pauses_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)

    def fail_after_request_timeout() -> None:
        clock.elapse(5.0)
        raise TransportError("offline")

    client = ScriptedClient([None, fail_after_request_timeout, None])

    assert _next_claim(client, route="default", queue="default", idle_timeout=1) is None

    assert clock.now == 8.0
    assert clock.sleeps == [1.0, 2.0]
    assert [call[2] for call in client.claim_calls] == [
        "r_ABCDEFGHIJKL",
        "r_MNOPQRSTUVWX",
        "r_MNOPQRSTUVWX",
    ]


def test_recovered_claim_is_renewed_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    claim = make_claim()
    client = ScriptedClient(
        [TransportError("response lost"), claim],
        heartbeats=[object()],
    )

    assert _next_claim(client, route="default", queue="default", idle_timeout=300) is claim

    assert [call[2] for call in client.claim_calls] == [
        "r_ABCDEFGHIJKL",
        "r_ABCDEFGHIJKL",
    ]
    assert client.heartbeat_calls == [("default", claim.task.id, claim.run_id, False)]
    assert clock.sleeps == [1.0]


def test_recovered_claim_crosses_real_client_http_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    expected = make_claim()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tasks/claim"):
            if len(requests) == 1:
                raise httpx.ConnectError("claim response lost", request=request)
            return httpx.Response(200, json=expected.model_dump(mode="json"))
        assert request.url.path.endswith(f"/tasks/{expected.task.id}/heartbeat")
        return httpx.Response(
            200,
            json={"lease_expires_at": "2026-08-20T12:10:00Z"},
        )

    client = Client(url="http://server.test", queue="default")
    client._http.close()
    client._http = httpx.Client(
        base_url="http://server.test/api/v2/",
        transport=httpx.MockTransport(handler),
    )
    try:
        actual = _next_claim(
            client,
            route="default",
            queue="default",
            idle_timeout=300,
        )
    finally:
        client.close()

    assert actual == expected
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "claim",
        "claim",
        "heartbeat",
    ]
    assert [json.loads(request.content)["run_id"] for request in requests] == [
        "r_ABCDEFGHIJKL",
        "r_ABCDEFGHIJKL",
        expected.run_id,
    ]


def test_claim_confirmation_uses_same_recovery_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    claim = make_claim()
    client = ScriptedClient(
        [TransportError("response lost"), claim],
        heartbeats=[TransportError("heartbeat response lost"), object()],
    )

    assert _next_claim(client, route="default", queue="default", idle_timeout=300) is claim

    assert len(client.claim_calls) == 2
    assert len(client.heartbeat_calls) == 2
    assert clock.sleeps == [1.0, 2.0]


def test_claim_returned_after_deadline_is_not_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    claim = make_claim()

    def delayed_claim() -> ClaimResponse:
        clock.elapse(300.0)
        return claim

    client = ScriptedClient([TransportError("response lost"), delayed_claim])

    with pytest.raises(TransportError, match="confirm a claim"):
        _next_claim(client, route="default", queue="default", idle_timeout=300)

    assert len(client.claim_calls) == 2
    assert client.heartbeat_calls == []


def test_confirmation_started_before_deadline_may_finish_after_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    claim = make_claim()

    def delayed_success() -> object:
        clock.elapse(300.0)
        return object()

    client = ScriptedClient(
        [TransportError("response lost"), claim],
        heartbeats=[delayed_success],
    )

    assert _next_claim(client, route="default", queue="default", idle_timeout=300) is claim
    assert clock.now == 301.0
    assert len(client.heartbeat_calls) == 1


def test_confirmation_failure_after_deadline_starts_no_repair_or_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    claim = make_claim()

    def delayed_claim() -> ClaimResponse:
        clock.elapse(289.0)
        return claim

    def delayed_failure() -> None:
        clock.elapse(11.0)
        raise TransportError("late heartbeat failure")

    client = ScriptedClient(
        [TransportError("response lost"), delayed_claim],
        heartbeats=[delayed_failure],
    )

    with pytest.raises(TransportError, match="late heartbeat failure"):
        _next_claim(client, route="default", queue="default", idle_timeout=300)

    assert len(client.heartbeat_calls) == 1
    assert len(client.repair_calls) == 1


def test_empty_response_ends_recovery_before_a_new_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)

    def slow_empty() -> None:
        clock.elapse(298.0)
        return None

    client = ScriptedClient(
        [TransportError("first outage"), slow_empty, TransportError("second outage"), None]
    )

    assert _next_claim(client, route="default", queue="default", idle_timeout=1) is None

    assert clock.now == 304.0
    assert clock.sleeps == [1.0, 1.0, 4.0]
    assert [call[2] for call in client.claim_calls] == [
        "r_ABCDEFGHIJKL",
        "r_ABCDEFGHIJKL",
        "r_MNOPQRSTUVWX",
        "r_MNOPQRSTUVWX",
    ]


def test_recovery_sleep_reaching_deadline_starts_no_new_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    monkeypatch.setattr("labtasker.worker._claim_backoff_delay", lambda _: 300.0)
    client = ScriptedClient([TransportError("offline"), make_claim()])

    with pytest.raises(TransportError, match="offline"):
        _next_claim(client, route="default", queue="default", idle_timeout=300)

    assert len(client.claim_calls) == 1
    assert clock.sleeps == [300.0]


@pytest.mark.parametrize("code", ["stale_run", "run_finalized"])
def test_lost_recovered_claim_is_discarded_without_stopping_worker(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    lost = make_claim()
    replacement = make_claim(
        task_id="t_MNOPQRSTUVWX",
        run_id="r_MNOPQRSTUVWX",
    )
    client = ScriptedClient(
        [TransportError("response lost"), lost, replacement],
        heartbeats=[APIError(409, code, "claim lost", {})],
    )

    assert _next_claim(client, route="default", queue="default", idle_timeout=300) is replacement

    assert [call[2] for call in client.claim_calls] == [
        "r_ABCDEFGHIJKL",
        "r_ABCDEFGHIJKL",
        "r_MNOPQRSTUVWX",
    ]
    assert len(client.heartbeat_calls) == 1


def test_local_repair_consumes_recovery_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    client = ScriptedClient(
        [TransportError("offline")],
        repair=lambda: clock.elapse(301.0),
    )

    with pytest.raises(TransportError, match="offline"):
        _next_claim(client, route="default", queue="default", idle_timeout=86_400)

    assert len(client.claim_calls) == 1
    assert len(client.repair_calls) == 1
    assert clock.sleeps == []


def test_failed_request_time_consumes_recovery_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)

    def fail_after_budget() -> None:
        clock.elapse(301.0)
        raise TransportError("request timed out")

    client = ScriptedClient([fail_after_budget])

    with pytest.raises(TransportError, match="request timed out"):
        _next_claim(client, route="default", queue="default", idle_timeout=86_400)

    assert len(client.claim_calls) == 1
    assert client.repair_calls == []
    assert clock.sleeps == []


def test_deterministic_claim_error_exits_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    error = APIError(401, "unauthorized", "bad token", {})
    client = ScriptedClient([error])

    with pytest.raises(APIError) as raised:
        _next_claim(client, route="default", queue="default", idle_timeout=300)

    assert raised.value is error
    assert len(client.claim_calls) == 1
    assert clock.sleeps == []


def test_claim_ownership_loss_uses_fresh_run_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    replacement = make_claim(run_id="r_MNOPQRSTUVWX")
    client = ScriptedClient([APIError(409, "stale_run", "claim expired", {}), replacement])

    assert _next_claim(client, route="default", queue="default", idle_timeout=300) is replacement
    assert [call[2] for call in client.claim_calls] == [
        "r_ABCDEFGHIJKL",
        "r_MNOPQRSTUVWX",
    ]


def test_claim_confirmation_deterministic_error_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    error = APIError(401, "unauthorized", "bad token", {})
    client = ScriptedClient(
        [TransportError("response lost"), make_claim()],
        heartbeats=[error],
    )

    with pytest.raises(APIError) as raised:
        _next_claim(client, route="default", queue="default", idle_timeout=300)

    assert raised.value is error
    assert len(client.heartbeat_calls) == 1


@pytest.mark.parametrize(
    ("multiplier", "expected"),
    [(0.8, 8.0), (1.2, 12.0)],
)
def test_claim_backoff_jitter_bounds_and_cap(
    monkeypatch: pytest.MonkeyPatch,
    multiplier: float,
    expected: float,
) -> None:
    monkeypatch.setattr("labtasker.worker.random.uniform", lambda *_: multiplier)
    assert _claim_backoff_delay(999) == expected


def test_server_error_retries_same_logical_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    install_clock(monkeypatch, clock)
    client = ScriptedClient([APIError(503, "database_busy", "busy", {}), None])

    assert _next_claim(client, route="default", queue="default", idle_timeout=0) is None

    assert [call[2] for call in client.claim_calls] == [
        "r_ABCDEFGHIJKL",
        "r_ABCDEFGHIJKL",
    ]
    assert clock.sleeps == [1.0]
