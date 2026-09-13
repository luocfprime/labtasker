import runpy
from pathlib import Path

TRIALS = [
    (
        "cobalt-leader",
        "cobalt-ablation",
        "running",
        {"validation_round": 5, "metrics": {"accuracy": 0.88}},
    ),
    (
        "cobalt-stop",
        "cobalt-ablation",
        "running",
        {"validation_round": 4, "metrics": {"accuracy": 0.70}},
    ),
    (
        "cobalt-near",
        "cobalt-ablation",
        "running",
        {"validation_round": 6, "metrics": {"accuracy": 0.74}},
    ),
    (
        "cobalt-early",
        "cobalt-ablation",
        "running",
        {"validation_round": 2, "metrics": {"accuracy": 0.52}},
    ),
    ("cobalt-no-report", "cobalt-ablation", "running", None),
    (
        "cobalt-complete",
        "cobalt-ablation",
        "succeeded",
        {"validation_round": 8, "metrics": {"accuracy": 0.92}},
    ),
    (
        "foreign-stop",
        "foreign-ablation",
        "running",
        {"validation_round": 5, "metrics": {"accuracy": 0.40}},
    ),
]


def seed(client, manifest, request):
    for index, (name, batch, state, progress) in enumerate(TRIALS):
        route = f"ablate-{index}"
        task = client.submit_task(
            {"drop_component": index},
            name=name,
            metadata={"batch": batch},
            routes=[route],
        )
        run_id = "r_h" + str(index).zfill(11)
        assert (
            request(
                manifest["url"],
                "/api/v2/queues/default/tasks/claim",
                manifest["token"],
                {"route": route, "run_id": run_id},
            )[0]
            == 200
        )
        if progress is not None:
            assert (
                request(
                    manifest["url"],
                    f"/api/v2/queues/default/tasks/{task.id}/progress",
                    manifest["token"],
                    {"run_id": run_id, "progress": progress},
                )[0]
                == 204
            )
        if state == "succeeded":
            assert (
                request(
                    manifest["url"],
                    f"/api/v2/queues/default/tasks/{task.id}/complete",
                    manifest["token"],
                    {"run_id": run_id, "result": {"accuracy": 0.92}},
                )[0]
                == 204
            )


def check(client, manifest, request):
    current = client.list_tasks(limit=100).items
    assert len(current) == len(manifest["initial"])
    by_id = {task.id: task.model_dump(mode="json") for task in current}
    initial = manifest["initial"]
    selected = [task_id for task_id, task in initial.items() if task["name"] == "cobalt-stop"]
    assert len(selected) == 1
    selected_id = selected[0]
    before = initial[selected_id]
    after = by_id[selected_id]
    assert after["status"] == "cancelled"
    assert after["progress"] == before["progress"]
    assert after["progress_updated_at"] == before["progress_updated_at"]
    assert after["progress_attempt"] == before["progress_attempt"] == 1
    assert after["finished_at"] is not None
    for field in set(before) - {"status", "updated_at", "finished_at"}:
        assert after[field] == before[field]
    for task_id, snapshot in initial.items():
        if task_id != selected_id:
            assert by_id[task_id] == snapshot


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
