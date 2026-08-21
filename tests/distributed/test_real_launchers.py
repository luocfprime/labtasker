from __future__ import annotations

import os
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from labtasker import Client
from labtasker.command_worker import run_command_worker
from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings

pytestmark = [
    pytest.mark.distributed_integration,
    pytest.mark.timeout(120),
    pytest.mark.skipif(os.name != "posix", reason="Command Workers require POSIX process groups"),
]


@pytest.fixture
def distributed_server_url(tmp_path: Path) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                ServerSettings(
                    host="127.0.0.1",
                    port=port,
                    database=tmp_path / "distributed.db",
                    token="secret",
                )
            ),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        pytest.fail("Distributed integration Server did not start.")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()


def configure_worker_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    server_url: str,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_URL", server_url)
    monkeypatch.setenv("LABTASKER_TOKEN", "secret")


def test_real_single_node_torchrun(
    distributed_server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    torchrun = shutil.which("torchrun")
    if torchrun is None:
        pytest.skip("torchrun is not installed")
    pytest.importorskip("torch")
    configure_worker_environment(monkeypatch, tmp_path, distributed_server_url)
    script = tmp_path / "torch_rank.py"
    script.write_text(
        """
import sys
import torch.distributed as dist
import labtasker

dist.init_process_group("gloo")
if dist.get_rank() == 0:
    labtasker.finish({
        "launcher": "torchrun",
        "value": sys.argv[1],
        "world_size": dist.get_world_size(),
    })
dist.barrier()
dist.destroy_process_group()
""",
        encoding="utf-8",
    )
    with Client(url=distributed_server_url, token="secret") as client:
        client.submit_task(
            {"value": "torch-value"},
            routes=["torchrun"],
            task_id="t_TORCHRUNTEST",
        )
    run_command_worker(
        [
            torchrun,
            "--standalone",
            "--nproc-per-node=2",
            str(script),
            "%{value}",
        ],
        route="torchrun",
        idle_timeout=0,
    )
    with Client(url=distributed_server_url, token="secret") as client:
        task = client.get_task("t_TORCHRUNTEST")
    assert task.status == "succeeded"
    assert task.result == {"launcher": "torchrun", "value": "torch-value", "world_size": 2}


def test_real_single_node_accelerate(
    distributed_server_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    accelerate = shutil.which("accelerate")
    if accelerate is None:
        pytest.skip("accelerate is not installed")
    pytest.importorskip("accelerate")
    configure_worker_environment(monkeypatch, tmp_path, distributed_server_url)
    # Exercise Accelerate's real multi-process launcher on CPU-only CI hosts.
    # Accelerator(cpu=True) selects gloo after torchrun-style rank variables exist.
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "")
    script = tmp_path / "accelerate_rank.py"
    script.write_text(
        """
import sys
from accelerate import Accelerator
import labtasker

accelerator = Accelerator(cpu=True)
if accelerator.is_main_process:
    labtasker.finish({
        "launcher": "accelerate",
        "value": sys.argv[1],
        "world_size": accelerator.num_processes,
    })
accelerator.wait_for_everyone()
""",
        encoding="utf-8",
    )
    with Client(url=distributed_server_url, token="secret") as client:
        client.submit_task(
            {"value": "accelerate-value"},
            routes=["accelerate"],
            task_id="t_ACCELERATET1",
        )
    run_command_worker(
        [
            accelerate,
            "launch",
            "--multi_gpu",
            "--num_processes=2",
            "--num_machines=1",
            "--mixed_precision=no",
            "--dynamo_backend=no",
            str(script),
            "%{value}",
        ],
        route="accelerate",
        idle_timeout=0,
    )
    with Client(url=distributed_server_url, token="secret") as client:
        task = client.get_task("t_ACCELERATET1")
    assert task.status == "succeeded"
    assert task.result == {
        "launcher": "accelerate",
        "value": "accelerate-value",
        "world_size": 2,
    }
