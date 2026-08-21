from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from labtasker.journal import LocalRunJournal, _task_slug
from labtasker.models import ClaimResponse, Task

HTTP_ENDPOINT = {
    "mode": "http",
    "url": "http://server",
    "socket": None,
    "directory": None,
    "database": None,
}


def claim(name: str | None = "SDXL / baseline 模型") -> ClaimResponse:
    task = Task.model_validate(
        {
            "id": "t_ABCDEFGHIJKL",
            "queue": "default",
            "status": "running",
            "name": name,
            "args": {"prompt": "猫"},
            "metadata": {},
            "priority": 0,
            "attempt": 2,
            "max_attempts": 3,
            "routes": ["gpu"],
            "result": {},
            "last_error": None,
            "last_route": "gpu",
            "created_at": datetime(2026, 8, 20, 14, 0, tzinfo=UTC),
            "updated_at": datetime(2026, 8, 20, 14, 35, 22, tzinfo=UTC),
            "started_at": datetime(2026, 8, 20, 14, 35, 22, tzinfo=UTC),
            "finished_at": None,
        },
        strict=True,
    )
    return ClaimResponse(
        task=task,
        run_id="r_ABCDEFGHIJKL",
        lease_expires_at=datetime(2026, 8, 20, 14, 40, 22, tzinfo=UTC),
    )


def test_create_semantic_layout_and_initial_snapshot(tmp_path: Path) -> None:
    journal = LocalRunJournal.create(
        claim=claim(),
        endpoint={**HTTP_ENDPOINT, "url": "http://127.0.0.1:8000/prefix"},
        queue="default",
        route="gpu",
        cwd=tmp_path,
    )
    assert journal.run_dir == (
        tmp_path
        / ".labtasker/runs/default"
        / "SDXL-baseline-模型__t_ABCDEFGHIJKL"
        / "20260820T143522Z__attempt-2__r_ABCDEFGHIJKL"
    )
    assert journal.log_path.read_bytes() == b""
    assert (tmp_path / ".labtasker/.gitignore").read_text() == "*\n!.gitignore\n"
    assert json.loads(journal.task_path.read_text()) == claim().task.model_dump(mode="json")
    run = json.loads(journal.run_path.read_text())
    assert run == {
        "schema_version": 1,
        "endpoint": {
            "mode": "http",
            "url": "http://127.0.0.1:8000/prefix",
            "socket": None,
            "directory": None,
            "database": None,
        },
        "queue": "default",
        "task_id": "t_ABCDEFGHIJKL",
        "run_id": "r_ABCDEFGHIJKL",
        "route": "gpu",
        "attempt": 2,
        "started_at": "2026-08-20T14:35:22Z",
        "finished_at": None,
        "phase": "running",
        "terminal_action": None,
        "acknowledged_at": None,
    }


def test_create_preserves_existing_local_gitignore(tmp_path: Path) -> None:
    labtasker_dir = tmp_path / ".labtasker"
    labtasker_dir.mkdir()
    gitignore = labtasker_dir / ".gitignore"
    gitignore.write_text("runs/\n")

    LocalRunJournal.create(
        claim=claim(),
        endpoint=HTTP_ENDPOINT,
        queue="default",
        route="gpu",
        cwd=tmp_path,
    )

    assert gitignore.read_text() == "runs/\n"


def test_terminal_updates_are_atomic_and_payload_specific(tmp_path: Path) -> None:
    journal = LocalRunJournal.create(
        claim=claim(),
        endpoint=HTTP_ENDPOINT,
        queue="default",
        route="gpu",
        cwd=tmp_path,
    )
    journal.reporting("complete", {"score": 0.9})
    assert json.loads(journal.result_path.read_text()) == {"score": 0.9}
    assert not journal.error_path.exists()
    assert json.loads(journal.run_path.read_text())["phase"] == "reporting"
    journal.reporting("complete", {"score": 0.9})
    with pytest.raises(ValueError, match="different terminal payload"):
        journal.reporting("complete", {"score": 1.0})
    assert json.loads(journal.result_path.read_text()) == {"score": 0.9}

    journal.acknowledged()
    recorded = json.loads(journal.run_path.read_text())
    assert recorded["phase"] == "acknowledged"
    assert recorded["terminal_action"] == "complete"
    assert recorded["finished_at"].endswith("Z")
    assert recorded["acknowledged_at"] == recorded["finished_at"]

    reopened = LocalRunJournal.open(journal.run_dir)
    assert reopened.phase == "acknowledged"
    assert reopened.terminal_action == "complete"
    assert reopened.read_result() == {"score": 0.9}


def test_fail_and_unclaim_payload_rules(tmp_path: Path) -> None:
    failed = LocalRunJournal.create(
        claim=claim("failed"),
        endpoint=HTTP_ENDPOINT,
        queue="default",
        route="gpu",
        cwd=tmp_path,
    )
    failed.reporting("fail", {"type": "ValueError", "message": "bad", "traceback": None})
    assert json.loads(failed.error_path.read_text())["type"] == "ValueError"

    unclaimed_claim = claim("unclaimed").model_copy(update={"run_id": "r_MNOPQRSTUVWX"})
    unclaimed = LocalRunJournal.create(
        claim=unclaimed_claim,
        endpoint=HTTP_ENDPOINT,
        queue="default",
        route="gpu",
        cwd=tmp_path,
    )
    unclaimed.reporting("unclaim")
    assert not unclaimed.result_path.exists()
    assert not unclaimed.error_path.exists()


def test_slug_uses_unicode_alnum_and_utf8_byte_limit() -> None:
    assert _task_slug(None) == "unnamed"
    assert _task_slug(" -- ") == "unnamed"
    assert _task_slug("A__B///模型") == "A-B-模型"
    slug = _task_slug("模" * 40)
    assert len(slug.encode("utf-8")) <= 80
    assert slug == "模" * 26


def test_create_collision_and_required_file_failure_are_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kwargs = {
        "claim": claim(),
        "endpoint": HTTP_ENDPOINT,
        "queue": "default",
        "route": "gpu",
        "cwd": tmp_path,
    }
    LocalRunJournal.create(**kwargs)  # type: ignore[arg-type]
    with pytest.raises(FileExistsError):
        LocalRunJournal.create(**kwargs)  # type: ignore[arg-type]
