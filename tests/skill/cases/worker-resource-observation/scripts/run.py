from __future__ import annotations

import runpy
from pathlib import Path


def observation_snapshot(client):
    return {
        worker.id: worker.model_dump(mode="json")
        for worker in client.list_workers(limit=1000).items
    }


def seed(client, manifest, request):
    workers = [
        (
            "w_ResourceA001",
            {
                "route": "llama",
                "status": "busy",
                "task_id": "t_ABCDEFGHIJKL",
                "metadata": {"node": "node-a", "gpu_ids": ["0"]},
            },
            [
                {"gpu_util_pct": 10, "temperature_c": 40},
                {"gpu_util_pct": 92, "memory_used_gb": 38},
            ],
        ),
        (
            "w_ResourceA002",
            {
                "route": "llama",
                "status": "idle",
                "task_id": None,
                "metadata": {"node": "node-a", "gpu_ids": ["1"]},
            },
            [{"gpu_util_pct": 14, "memory_used_gb": 6}],
        ),
        (
            "w_ResourceB001",
            {
                "route": "bert",
                "status": "busy",
                "task_id": "t_BCDEFGHIJKLM",
                "metadata": {"node": "node-b", "gpu_ids": ["0"]},
            },
            [{"gpu_util_pct": 77, "memory_used_gb": 31}],
        ),
    ]
    for worker_id, report, telemetry_reports in workers:
        status, _ = request(
            manifest["url"],
            f"/api/v2/queues/default/workers/{worker_id}",
            manifest["token"],
            report,
            "PUT",
        )
        assert status == 204
        for telemetry in telemetry_reports:
            status, _ = request(
                manifest["url"],
                f"/api/v2/queues/default/workers/{worker_id}/telemetry",
                manifest["token"],
                {"telemetry": telemetry},
                "POST",
            )
            assert status == 204
    manifest["initial_workers"] = observation_snapshot(client)


def check(client, manifest, request):
    del request
    assert observation_snapshot(client) == manifest["initial_workers"]
    current_tasks = {
        task.id: task.model_dump(mode="json") for task in client.list_tasks(limit=1000).items
    }
    assert current_tasks == manifest["initial"]


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
