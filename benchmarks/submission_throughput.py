from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn

import labtasker
from labtasker import Client
from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings

TOKEN = "benchmark-secret"


def positive_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 99_999_999:
        raise argparse.ArgumentTypeError("count must be between 1 and 99,999,999")
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure sequential Task submission through the public Python and Bash APIs."
    )
    parser.add_argument("--python-count", type=positive_count, default=500)
    parser.add_argument("--bash-count", type=positive_count, default=25)
    return parser.parse_args()


@contextmanager
def running_server(database: Path) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    application = create_app(
        ServerSettings(host="127.0.0.1", port=port, database=database, token=TOKEN)
    )
    server = uvicorn.Server(
        uvicorn.Config(application, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        raise RuntimeError("Benchmark Server did not start.")
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Benchmark Server did not stop.")


def measure_python(server_url: str, count: int) -> dict[str, float | int]:
    with Client(url=server_url, token=TOKEN) as client:
        client.list_queues()
        started = time.perf_counter()
        for index in range(count):
            client.submit_task(
                {"index": index, "source": "python"},
                metadata={"benchmark": "python"},
                routes=["submission-benchmark"],
                task_id=f"t_PYBN{index:08d}",
            )
        elapsed = time.perf_counter() - started
        verified = client.count_tasks(filter='metadata.benchmark == "python"')
    return measurement(count, verified, elapsed)


def measure_python_functions(server_url: str, count: int) -> dict[str, float | int]:
    os.environ.update(
        {
            "LABTASKER_URL": server_url,
            "LABTASKER_TOKEN": TOKEN,
            "LABTASKER_QUEUE": "default",
        }
    )
    labtasker.list_queues()
    started = time.perf_counter()
    for index in range(count):
        labtasker.submit_task(
            {"index": index, "source": "function"},
            metadata={"benchmark": "function"},
            routes=["submission-benchmark"],
            task_id=f"t_FNBN{index:08d}",
        )
    elapsed = time.perf_counter() - started
    verified = labtasker.count_tasks(filter='metadata.benchmark == "function"')
    return measurement(count, verified, elapsed)


def measure_bash(server_url: str, count: int) -> dict[str, float | int]:
    bash = shutil.which("bash")
    if bash is None:
        raise RuntimeError("Bash is required for the Bash/CLI benchmark.")
    script = r"""
set -euo pipefail
for ((index = 0; index < BASH_COUNT; index++)); do
  printf -v task_id 't_CLBN%08d' "$index"
  printf -v args '{"index":%d,"source":"bash"}' "$index"
  "$PYTHON_EXECUTABLE" -m labtasker task submit \
    --id "$task_id" \
    --args "$args" \
    --metadata '{"benchmark":"bash"}' \
    --route submission-benchmark \
    >/dev/null
done
"""
    environment = dict(os.environ)
    environment.update(
        {
            "BASH_COUNT": str(count),
            "PYTHON_EXECUTABLE": sys.executable,
            "LABTASKER_URL": server_url,
            "LABTASKER_TOKEN": TOKEN,
            "LABTASKER_QUEUE": "default",
        }
    )
    started = time.perf_counter()
    result = subprocess.run(
        [bash, "-c", script],
        env=environment,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=max(30, count * 3),
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(f"Bash submission loop failed:\n{result.stderr}")
    with Client(url=server_url, token=TOKEN) as client:
        verified = client.count_tasks(filter='metadata.benchmark == "bash"')
    return measurement(count, verified, elapsed)


def measurement(requested: int, verified: int, elapsed: float) -> dict[str, float | int]:
    if verified != requested:
        raise RuntimeError(f"Expected {requested} Tasks after submission, found {verified}.")
    return {
        "tasks": requested,
        "verified_tasks": verified,
        "seconds": round(elapsed, 6),
        "tasks_per_second": round(requested / elapsed, 3),
    }


def main() -> None:
    arguments = parse_args()
    result: dict[str, dict[str, float | int]] = {}
    with tempfile.TemporaryDirectory(prefix="labtasker-submission-benchmark-") as directory:
        root = Path(directory)
        with running_server(root / "python-client.db") as server_url:
            result["python_reused_client"] = measure_python(server_url, arguments.python_count)
        with running_server(root / "python-functions.db") as server_url:
            result["python_function_api"] = measure_python_functions(
                server_url, arguments.python_count
            )
        with running_server(root / "bash-cli.db") as server_url:
            result["bash_cli_process_per_task"] = measure_bash(server_url, arguments.bash_count)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
