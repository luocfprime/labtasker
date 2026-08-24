from __future__ import annotations

import argparse
import json
import socket
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from labtasker import Client
from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings

TOKEN = "concurrent-benchmark-secret"
ROUTE = "concurrent-benchmark"


def positive_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 99_999_999:
        raise argparse.ArgumentTypeError("count must be between 1 and 99,999,999")
    return count


def concurrency_count(value: str) -> int:
    count = int(value)
    if not 1 <= count <= 999:
        raise argparse.ArgumentTypeError("concurrency must be between 1 and 999")
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure concurrent Task submission and claim/completion throughput."
    )
    parser.add_argument("--tasks", type=positive_count, default=500)
    parser.add_argument("--clients", type=concurrency_count, default=8)
    parser.add_argument("--workers", type=concurrency_count, default=8)
    return parser.parse_args()


@contextmanager
def running_server(database: Path) -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(
                ServerSettings(
                    host="127.0.0.1",
                    port=port,
                    database=database,
                    token=TOKEN,
                )
            ),
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
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


def run_concurrently(
    concurrency: int,
    operation: Callable[[int, threading.Barrier], list[str]],
) -> tuple[list[str], float]:
    barrier = threading.Barrier(concurrency + 1)
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(operation, index, barrier) for index in range(concurrency)]
        started = time.perf_counter()
        barrier.wait()
        completed = [task_id for future in futures for task_id in future.result()]
    return completed, time.perf_counter() - started


def measurement(tasks: int, concurrency: int, elapsed: float) -> dict[str, float | int]:
    return {
        "tasks": tasks,
        "concurrency": concurrency,
        "seconds": round(elapsed, 6),
        "tasks_per_second": round(tasks / elapsed, 3),
    }


def measure_submission(server_url: str, tasks: int, clients: int) -> dict[str, float | int]:
    def submit(client_index: int, barrier: threading.Barrier) -> list[str]:
        submitted: list[str] = []
        with Client(url=server_url, token=TOKEN) as client:
            client.list_queues()
            barrier.wait()
            for task_index in range(client_index, tasks, clients):
                task_id = f"t_CSBN{task_index:08d}"
                client.submit_task(
                    {"index": task_index},
                    metadata={"benchmark": "concurrent-submit"},
                    routes=[ROUTE],
                    task_id=task_id,
                )
                submitted.append(task_id)
        return submitted

    submitted, elapsed = run_concurrently(clients, submit)
    with Client(url=server_url, token=TOKEN) as client:
        verified = client.count_tasks(filter='metadata.benchmark == "concurrent-submit"')
    if len(submitted) != tasks or len(set(submitted)) != tasks or verified != tasks:
        raise RuntimeError(
            f"Submission verification failed: completed={len(submitted)}, "
            f"unique={len(set(submitted))}, stored={verified}, expected={tasks}."
        )
    return measurement(tasks, clients, elapsed)


def measure_claim_complete(server_url: str, tasks: int, workers: int) -> dict[str, float | int]:
    with Client(url=server_url, token=TOKEN) as client:
        for task_index in range(tasks):
            client.submit_task(
                {"index": task_index},
                metadata={"benchmark": "claim-complete"},
                routes=[ROUTE],
                task_id=f"t_CWBN{task_index:08d}",
            )

    def work(worker_index: int, barrier: threading.Barrier) -> list[str]:
        completed: list[str] = []
        claim_index = 0
        with Client(url=server_url, token=TOKEN) as client:
            client.list_queues()
            barrier.wait()
            while True:
                run_id = f"r_C{worker_index:03d}{claim_index:08d}"
                claim_index += 1
                claim = client._claim(route=ROUTE, run_id=run_id, queue="default")
                if claim is None:
                    break
                client._complete(
                    task_id=claim.task.id,
                    run_id=claim.run_id,
                    result={"worker": worker_index},
                    queue="default",
                )
                completed.append(claim.task.id)
        return completed

    completed, elapsed = run_concurrently(workers, work)
    with Client(url=server_url, token=TOKEN) as client:
        verified = client.count_tasks(
            status="succeeded",
            filter='metadata.benchmark == "claim-complete"',
        )
    if len(completed) != tasks or len(set(completed)) != tasks or verified != tasks:
        raise RuntimeError(
            f"Worker verification failed: completed={len(completed)}, "
            f"unique={len(set(completed))}, stored={verified}, expected={tasks}."
        )
    return measurement(tasks, workers, elapsed)


def main() -> None:
    arguments = parse_args()
    with tempfile.TemporaryDirectory(prefix="labtasker-concurrent-benchmark-") as directory:
        root = Path(directory)
        with running_server(root / "submission.db") as server_url:
            submission = measure_submission(server_url, arguments.tasks, arguments.clients)
        with running_server(root / "workers.db") as server_url:
            claim_complete = measure_claim_complete(
                server_url,
                arguments.tasks,
                arguments.workers,
            )
    print(
        json.dumps(
            {
                "concurrent_python_submission": submission,
                "concurrent_claim_complete": claim_complete,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
