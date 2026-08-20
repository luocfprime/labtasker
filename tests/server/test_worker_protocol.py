from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings
from labtasker_server.services.tasks import HEARTBEAT_TIMEOUT_US

TASK_1 = "t_ABCDEFGHIJKL"
TASK_2 = "t_MNOPQRSTUVWX"
TASK_3 = "t_0123456789-_"
RUN_1 = "r_ABCDEFGHIJKL"
RUN_2 = "r_MNOPQRSTUVWX"
RUN_3 = "r_0123456789-_"


class Clock:
    def __init__(self, value: int = 1_700_000_000_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, microseconds: int = 1) -> None:
        self.value += microseconds


def make_client(database_path: Path, clock: Clock) -> TestClient:
    return TestClient(
        create_app(
            ServerSettings(database=database_path),
            now_us=clock,
        )
    )


def submit(
    client: TestClient,
    task_id: str = TASK_1,
    **body: object,
) -> dict[str, object]:
    response = client.put(f"/api/v2/queues/default/tasks/{task_id}", json=body)
    assert response.status_code == 201
    return response.json()


def claim(
    client: TestClient,
    run_id: str = RUN_1,
    route: str = "default",
) -> dict[str, object]:
    response = client.post(
        "/api/v2/queues/default/tasks/claim",
        json={"route": route, "run_id": run_id},
    )
    assert response.status_code == 200
    return response.json()


def action_url(task_id: str, action: str) -> str:
    return f"/api/v2/queues/default/tasks/{task_id}/{action}"


def test_claim_uses_route_priority_and_pending_order(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client, TASK_1, priority=1, routes=["a"])
        clock.advance()
        submit(client, TASK_2, priority=2, routes=["a", "b"])
        clock.advance()
        submit(client, TASK_3, priority=2, routes=["a"])

        assert claim(client, RUN_1, "a")["task"]["id"] == TASK_2
        assert claim(client, RUN_2, "a")["task"]["id"] == TASK_3
        assert claim(client, RUN_3, "a")["task"]["id"] == TASK_1
        empty = client.post(
            "/api/v2/queues/default/tasks/claim",
            json={"route": "unknown", "run_id": "r_zzzzzzzzzzzz"},
        )
        assert empty.status_code == 204
        assert empty.content == b""


def test_claim_is_idempotent_and_fences_request_identity(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client)
        first = claim(client)
        repeated = claim(client)
        assert repeated == first
        assert first["task"]["status"] == "running"
        assert first["task"]["attempt"] == 1
        assert first["task"]["last_route"] == "default"
        assert first["task"]["started_at"] == first["task"]["updated_at"]
        assert set(client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()).isdisjoint(
            {"run_id", "lease_expires_at"}
        )

        wrong_route = client.post(
            "/api/v2/queues/default/tasks/claim",
            json={"route": "other", "run_id": RUN_1},
        )
        assert wrong_route.status_code == 409
        assert wrong_route.json()["error"]["code"] == "run_id_conflict"


def test_heartbeat_renews_lease_without_changing_task_updated_at(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client)
        owned = claim(client)
        task_before = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        clock.advance(10_000_000)
        heartbeat = client.post(action_url(TASK_1, "heartbeat"), json={"run_id": RUN_1})
        assert heartbeat.status_code == 200
        expected = (
            datetime.fromtimestamp(
                (clock.value + HEARTBEAT_TIMEOUT_US) / 1_000_000,
                UTC,
            )
            .isoformat()
            .replace("+00:00", "Z")
        )
        assert heartbeat.json() == {"lease_expires_at": expected}
        assert heartbeat.json()["lease_expires_at"] != owned["lease_expires_at"]
        task_after = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert task_after["updated_at"] == task_before["updated_at"]


def test_complete_is_idempotent_and_contradictory_actions_conflict(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client)
        claim(client)
        clock.advance()
        body = {"run_id": RUN_1, "result": {"accuracy": 0.9}}
        assert client.post(action_url(TASK_1, "complete"), json=body).status_code == 204
        assert client.post(action_url(TASK_1, "complete"), json=body).status_code == 204

        task = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert task["status"] == "succeeded"
        assert task["result"] == {"accuracy": 0.9}
        assert task["finished_at"] == task["updated_at"]

        contradictory = client.post(
            action_url(TASK_1, "fail"),
            json={
                "run_id": RUN_1,
                "error": {"type": "Error", "message": "late", "traceback": None},
            },
        )
        assert contradictory.status_code == 409
        assert contradictory.json()["error"] == {
            "code": "run_finalized",
            "message": "This run has already been finalized.",
            "details": {"action": "complete"},
        }
        heartbeat = client.post(action_url(TASK_1, "heartbeat"), json={"run_id": RUN_1})
        assert heartbeat.status_code == 409
        assert heartbeat.json()["error"]["details"] == {"action": "complete"}


def test_fail_retries_then_exhausts_attempt_budget(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client, max_attempts=2)
        claim(client, RUN_1)
        clock.advance()
        failure = {
            "run_id": RUN_1,
            "error": {
                "type": "ValueError",
                "message": "invalid size",
                "traceback": "trace",
            },
        }
        assert client.post(action_url(TASK_1, "fail"), json=failure).status_code == 204
        first = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert first["status"] == "pending"
        assert first["attempt"] == 1
        assert first["last_error"] | {"occurred_at": None} == {
            "type": "ValueError",
            "message": "invalid size",
            "traceback": "trace",
            "occurred_at": None,
            "attempt": 1,
            "run_id": RUN_1,
        }

        claim(client, RUN_2)
        clock.advance()
        second_failure = {
            "run_id": RUN_2,
            "error": {"type": "RuntimeError", "message": "again", "traceback": None},
        }
        assert client.post(action_url(TASK_1, "fail"), json=second_failure).status_code == 204
        final = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert final["status"] == "failed"
        assert final["attempt"] == 2
        assert final["last_error"]["run_id"] == RUN_2
        assert final["last_error"]["attempt"] == 2


def test_lost_fail_response_retry_cannot_modify_next_run(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client, max_attempts=3)
        claim(client, RUN_1)
        fail_body = {
            "run_id": RUN_1,
            "error": {"type": "Error", "message": "first", "traceback": None},
        }
        assert client.post(action_url(TASK_1, "fail"), json=fail_body).status_code == 204
        claim(client, RUN_2)

        duplicate = client.post(action_url(TASK_1, "fail"), json=fail_body)
        assert duplicate.status_code == 204
        still_running = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert still_running["status"] == "running"
        assert still_running["attempt"] == 2
        assert still_running["last_error"]["run_id"] == RUN_1


def test_unclaim_rolls_back_only_current_attempt_and_preserves_error(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client)
        claim(client, RUN_1)
        client.post(
            action_url(TASK_1, "fail"),
            json={
                "run_id": RUN_1,
                "error": {"type": "Error", "message": "charged", "traceback": None},
            },
        )
        claim(client, RUN_2)
        clock.advance()
        assert (
            client.post(
                action_url(TASK_1, "unclaim"),
                json={"run_id": RUN_2},
            ).status_code
            == 204
        )
        task = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert task["status"] == "pending"
        assert task["attempt"] == 1
        assert task["last_error"]["run_id"] == RUN_1
        assert task["finished_at"] == task["updated_at"]


def test_cancel_requeue_and_delete_lifecycle(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        created = submit(client)
        cancelled = client.post(action_url(TASK_1, "cancel"))
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["started_at"] is None
        assert cancelled.json()["finished_at"] is None
        repeated = client.post(action_url(TASK_1, "cancel"))
        assert repeated.json()["updated_at"] == cancelled.json()["updated_at"]
        assert repeated.json()["result"] == created["result"]

        clock.advance()
        requeued = client.post(action_url(TASK_1, "requeue"))
        assert requeued.status_code == 200
        assert requeued.json()["status"] == "pending"
        assert requeued.json()["attempt"] == 0
        assert requeued.json()["last_error"] is None

        claim(client)
        running_delete = client.delete(f"/api/v2/queues/default/tasks/{TASK_1}")
        assert running_delete.status_code == 409
        assert running_delete.json()["error"]["code"] == "task_running"
        running_cancel = client.post(action_url(TASK_1, "cancel"))
        assert running_cancel.json()["finished_at"] is not None
        stale_heartbeat = client.post(
            action_url(TASK_1, "heartbeat"),
            json={"run_id": RUN_1},
        )
        assert stale_heartbeat.status_code == 409
        assert stale_heartbeat.json()["error"]["details"] == {"action": "cancel"}

        assert client.delete(f"/api/v2/queues/default/tasks/{TASK_1}").status_code == 204
        assert client.delete(f"/api/v2/queues/default/tasks/{TASK_1}").status_code == 204
        assert (
            client.put(
                f"/api/v2/queues/default/tasks/{TASK_1}",
                json={"args": {"new": True}},
            ).status_code
            == 201
        )


def test_complete_at_lease_deadline_applies_expiry_before_rejecting(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client, max_attempts=2)
        claim(client)
        clock.advance(HEARTBEAT_TIMEOUT_US)
        late = client.post(
            action_url(TASK_1, "complete"),
            json={"run_id": RUN_1, "result": {"too": "late"}},
        )
        assert late.status_code == 409
        assert late.json()["error"]["details"] == {"action": "heartbeat_expired"}
        task = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert task["status"] == "pending"
        assert task["attempt"] == 1
        assert task["last_error"] == {
            "type": "HeartbeatTimeout",
            "message": "Heartbeat lease expired.",
            "traceback": None,
            "occurred_at": task["finished_at"],
            "attempt": 1,
            "run_id": RUN_1,
        }


def test_expiry_scan_exhausts_last_attempt(database_path: Path) -> None:
    clock = Clock()
    app = create_app(ServerSettings(database=database_path), now_us=clock)
    with TestClient(app) as client:
        submit(client, max_attempts=1)
        claim(client)
        clock.advance(HEARTBEAT_TIMEOUT_US)
        assert app.state.task_service.expire_leases() == 1
        assert app.state.task_service.expire_leases() == 0
        task = client.get(f"/api/v2/queues/default/tasks/{TASK_1}").json()
        assert task["status"] == "failed"
        assert task["last_error"]["type"] == "HeartbeatTimeout"


def test_oversized_completion_keeps_run_active_for_smaller_retry(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client, args={"input": "x" * 600_000})
        claim(client)
        oversized = client.post(
            action_url(TASK_1, "complete"),
            json={"run_id": RUN_1, "result": {"output": "y" * 600_000}},
        )
        assert oversized.status_code == 422
        assert oversized.json()["error"]["code"] == "task_data_too_large"
        assert (
            client.post(
                action_url(TASK_1, "heartbeat"),
                json={"run_id": RUN_1},
            ).status_code
            == 200
        )
        assert (
            client.post(
                action_url(TASK_1, "complete"),
                json={"run_id": RUN_1, "result": {"output": "small"}},
            ).status_code
            == 204
        )


def test_worker_request_schemas_reject_unknown_or_missing_fields(database_path: Path) -> None:
    clock = Clock()
    with make_client(database_path, clock) as client:
        submit(client)
        claim(client)
        cases = [
            ("heartbeat", {"run_id": RUN_1, "progress": 0.5}),
            ("complete", {"run_id": RUN_1}),
            ("unclaim", {"run_id": RUN_1, "reason": "no"}),
            (
                "fail",
                {
                    "run_id": RUN_1,
                    "error": {"type": "Error", "message": "x", "traceback": None, "x": 1},
                },
            ),
        ]
        for action, body in cases:
            response = client.post(action_url(TASK_1, action), json=body)
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "invalid_request"
