from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

import pytest

from labtasker import Client
from labtasker.command_worker import run_command_worker


@pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups")
def test_fake_launcher_has_one_outer_claim_and_heartbeat_source(
    server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")
    with Client(url=server_url, token="secret") as client:
        client.submit_task(
            {"value": "same input for every rank"},
            name="fake distributed",
            routes=["distributed"],
            task_id="t_DISTRIBUTED1",
        )

    rank_script = tmp_path / "rank.py"
    rank_script.write_text(
        """
import json, os, sys, threading, time
from pathlib import Path
import labtasker

before = [thread.name for thread in threading.enumerate()]
info = labtasker.task_info()
after = [thread.name for thread in threading.enumerate()]
rank = int(os.environ["RANK"])
record = {
    "rank": rank,
    "value": sys.argv[1],
    "task_id": info.id,
    "run_id": info.run_id,
    "before_threads": before,
    "after_threads": after,
}
Path(sys.argv[2], f"rank-{rank}.json").write_text(json.dumps(record))
if rank == 0:
    labtasker.finish({"main_rank": rank, "world_size": int(os.environ["WORLD_SIZE"])})
time.sleep(0.25)
""",
        encoding="utf-8",
    )
    launcher_script = tmp_path / "launcher.py"
    launcher_script.write_text(
        """
import os, subprocess, sys
processes = []
for rank in range(3):
    environment = dict(os.environ)
    environment.update(WORLD_SIZE="3", RANK=str(rank), LOCAL_RANK=str(rank))
    processes.append(subprocess.Popen(
        [sys.executable, sys.argv[1], sys.argv[2], sys.argv[3]], env=environment
    ))
raise SystemExit(max(process.wait() for process in processes))
""",
        encoding="utf-8",
    )

    heartbeat_threads: set[int] = set()
    original_heartbeat = Client._heartbeat

    def counted_heartbeat(self: Client, **kwargs: object) -> object:
        heartbeat_threads.add(threading.get_ident())
        return original_heartbeat(self, **kwargs)

    monkeypatch.setattr(Client, "_heartbeat", counted_heartbeat)
    monkeypatch.setattr("labtasker.worker.HEARTBEAT_INTERVAL_SECONDS", 0.05)
    records = tmp_path / "rank-records"
    records.mkdir()
    run_command_worker(
        [
            sys.executable,
            str(launcher_script),
            str(rank_script),
            "%{value}",
            str(records),
        ],
        route="distributed",
        idle_timeout=0,
    )

    rank_records = [json.loads((records / f"rank-{rank}.json").read_text()) for rank in range(3)]
    assert [record["rank"] for record in rank_records] == [0, 1, 2]
    assert {record["value"] for record in rank_records} == {"same input for every rank"}
    assert {record["task_id"] for record in rank_records} == {"t_DISTRIBUTED1"}
    assert len({record["run_id"] for record in rank_records}) == 1
    assert all(
        not any(name.startswith("labtasker-heartbeat") for name in record["before_threads"])
        and not any(name.startswith("labtasker-heartbeat") for name in record["after_threads"])
        for record in rank_records
    )
    assert len(heartbeat_threads) == 1
    with Client(url=server_url, token="secret") as client:
        task = client.get_task("t_DISTRIBUTED1")
    assert task.status == "succeeded"
    assert task.attempt == 1
    assert task.result == {"main_rank": 0, "world_size": 3}
