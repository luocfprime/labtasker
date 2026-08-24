from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from labtasker import Client

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo/basic"
LOCAL_ENVIRONMENT_NAMES = (
    "LABTASKER_URL",
    "LABTASKER_TOKEN",
    "LABTASKER_SOCKET",
    "LABTASKER_LOCAL_DIRECTORY",
    "LABTASKER_QUEUE",
)
EXPECTED = {
    (1, 2): 3,
    (2, 3): 5,
    (3, 5): 8,
    (5, 8): 13,
    (8, 13): 21,
    (13, 21): 34,
}


def _local_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in LOCAL_ENVIRONMENT_NAMES:
        environment.pop(name, None)
    return environment


def _run(directory: Path, script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DEMO / script)],
        cwd=directory,
        env=_local_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _stop_server(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "labtasker_server", "stop"],
        cwd=directory,
        env=_local_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.mark.skipif(os.name != "posix", reason="the demo uses automatic local mode")
def test_basic_demo_runs_exact_documented_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    for name in LOCAL_ENVIRONMENT_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)

    try:
        submitted = _run(tmp_path, "submit.py")
        assert submitted.returncode == 0, submitted.stderr
        assert submitted.stdout.count("submitted task_id=") == len(EXPECTED)
        assert "[labtasker] connected server=local transport=unix" in submitted.stderr

        worked = _run(tmp_path, "worker.py")
        assert worked.returncode == 0, worked.stderr
        assert worked.stdout.count("completed expression=") == len(EXPECTED)
        assert "INFO [labtasker] Worker idle timeout reached; stopping normally." in worked.stderr

        with Client() as client:
            page = client.list_tasks(status="succeeded", limit=100)
        actual = {
            (int(task.args["left"]), int(task.args["right"])): task.result["total"]
            for task in page.items
        }
        assert actual == EXPECTED
        assert len(list((tmp_path / ".labtasker/runs/default").glob("**/result.json"))) == len(
            EXPECTED
        )
    finally:
        stopped = _stop_server(tmp_path)
        assert stopped.returncode == 0, stopped.stderr
