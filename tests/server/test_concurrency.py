from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from labtasker_server.database import Database
from labtasker_server.errors import DomainError
from labtasker_server.schemas import TaskCreate, TaskUpdate
from labtasker_server.services.queues import QueueService
from labtasker_server.services.tasks import HEARTBEAT_TIMEOUT_US, TaskService

TASK_ID = "t_ABCDEFGHIJKL"
RUN_1 = "r_ABCDEFGHIJKL"
RUN_2 = "r_MNOPQRSTUVWX"


class Clock:
    def __init__(self) -> None:
        self.value = 1_700_000_000_000_000

    def __call__(self) -> int:
        return self.value


def services(
    database_path: Path, clock: Clock
) -> tuple[Database, Database, TaskService, TaskService]:
    first_database = Database(database_path)
    first_database.initialize()
    # Both connections model concurrent commands inside the one owning Server process.
    assert first_database._ownership_fd is not None
    second_database = Database(
        database_path,
        ownership_fd=first_database._ownership_fd,
    )
    first = TaskService(first_database, now_us=clock)
    second = TaskService(second_database, now_us=clock)
    first.create("default", TASK_ID, TaskCreate())
    return first_database, second_database, first, second


def captured(operation: Callable[[], object]) -> object:
    try:
        return operation()
    except DomainError as error:
        return error


def test_two_workers_racing_for_one_task_have_one_winner(database_path: Path) -> None:
    clock = Clock()
    first_db, second_db, first, second = services(database_path, clock)
    barrier = Barrier(2)

    def claim(service: TaskService, run_id: str) -> object:
        barrier.wait()
        return service.claim("default", "default", run_id)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(claim, first, RUN_1),
                executor.submit(claim, second, RUN_2),
            ]
            results = [future.result() for future in futures]
        winners = [result for result in results if result is not None]
        assert len(winners) == 1
        assert winners[0].task.status == "running"
        assert winners[0].task.attempt == 1
    finally:
        first_db.dispose()
        second_db.dispose()


def test_concurrent_same_run_claim_retries_return_same_task(database_path: Path) -> None:
    clock = Clock()
    first_db, second_db, first, second = services(database_path, clock)
    barrier = Barrier(2)

    def claim(service: TaskService) -> object:
        barrier.wait()
        return service.claim("default", "default", RUN_1)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [
                executor.submit(claim, first),
                executor.submit(claim, second),
            ]
            claims = [future.result() for future in results]
        assert claims[0] == claims[1]
        assert claims[0] is not None
        assert claims[0].task.id == TASK_ID
        assert claims[0].task.attempt == 1
    finally:
        first_db.dispose()
        second_db.dispose()


def test_complete_racing_cancel_has_one_lifecycle_winner(database_path: Path) -> None:
    clock = Clock()
    first_db, second_db, first, second = services(database_path, clock)
    first.claim("default", "default", RUN_1)
    barrier = Barrier(2)

    def complete() -> object:
        barrier.wait()
        return captured(lambda: first.complete("default", TASK_ID, RUN_1, {"ok": True}))

    def cancel() -> object:
        barrier.wait()
        return captured(lambda: second.cancel("default", TASK_ID))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = [executor.submit(complete), executor.submit(cancel)]
            outcomes = [future.result() for future in results]
        task = first.get("default", TASK_ID)
        assert task.status in {"succeeded", "cancelled"}
        errors = [outcome for outcome in outcomes if isinstance(outcome, DomainError)]
        assert len(errors) == 1
        if task.status == "succeeded":
            assert errors[0].code == "task_state_conflict"
            assert task.result == {"ok": True}
        else:
            assert errors[0].code == "run_finalized"
            assert errors[0].details == {"action": "cancel"}
    finally:
        first_db.dispose()
        second_db.dispose()


def test_complete_racing_expiry_commits_expiry_once(database_path: Path) -> None:
    clock = Clock()
    first_db, second_db, first, second = services(database_path, clock)
    first.claim("default", "default", RUN_1)
    clock.value += HEARTBEAT_TIMEOUT_US
    barrier = Barrier(2)

    def complete() -> object:
        barrier.wait()
        return captured(lambda: first.complete("default", TASK_ID, RUN_1, {"late": True}))

    def expire() -> object:
        barrier.wait()
        return second.expire_leases()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = [executor.submit(complete), executor.submit(expire)]
            complete_outcome, expiry_count = [future.result() for future in outcomes]
        assert isinstance(complete_outcome, DomainError)
        assert complete_outcome.code == "run_finalized"
        assert complete_outcome.details == {"action": "heartbeat_expired"}
        assert expiry_count in {0, 1}
        task = first.get("default", TASK_ID)
        assert task.status == "pending"
        assert task.last_error is not None
        assert task.last_error.type == "HeartbeatTimeout"
        assert task.last_error.run_id == RUN_1
    finally:
        first_db.dispose()
        second_db.dispose()


def test_update_racing_claim_is_atomic(database_path: Path) -> None:
    clock = Clock()
    first_db, second_db, first, second = services(database_path, clock)
    barrier = Barrier(2)

    def claim() -> object:
        barrier.wait()
        return first.claim("default", "default", RUN_1)

    def update() -> object:
        barrier.wait()
        return captured(
            lambda: second.update_task(
                "default",
                TASK_ID,
                TaskUpdate(args={"version": 2}),
            )
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = [executor.submit(claim), executor.submit(update)]
            claim_outcome, update_outcome = [future.result() for future in outcomes]
        assert claim_outcome is not None
        final = first.get("default", TASK_ID)
        assert final.status == "running"
        if isinstance(update_outcome, DomainError):
            assert update_outcome.code == "task_running"
            assert final.args == {}
        else:
            assert final.args == {"version": 2}
            assert claim_outcome.task.args == {"version": 2}
    finally:
        first_db.dispose()
        second_db.dispose()


def test_claim_racing_cascade_queue_delete_is_serialized(database_path: Path) -> None:
    clock = Clock()
    first_db, second_db, first, _ = services(database_path, clock)
    queues = QueueService(second_db)
    barrier = Barrier(2)

    def claim() -> object:
        barrier.wait()
        return captured(lambda: first.claim("default", "default", RUN_1))

    def delete() -> object:
        barrier.wait()
        return captured(lambda: queues.delete("default", cascade=True))

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            claim_outcome, delete_outcome = [
                future.result() for future in (executor.submit(claim), executor.submit(delete))
            ]
        if isinstance(claim_outcome, DomainError):
            assert claim_outcome.code == "queue_not_found"
            assert delete_outcome is None
            assert queues.list() == []
        else:
            assert claim_outcome is not None
            assert isinstance(delete_outcome, DomainError)
            assert delete_outcome.code == "queue_has_running_tasks"
            assert first.get("default", TASK_ID).status == "running"
    finally:
        first_db.dispose()
        second_db.dispose()
