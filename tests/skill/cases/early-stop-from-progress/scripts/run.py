import runpy
from pathlib import Path

BATCH = "orchid-tuning"
TRIALS = [
    (
        "orchid-alpha",
        BATCH,
        "running",
        {"step": 1200, "metrics": {"val_loss": 0.45, "best_val_loss": 0.42}},
    ),
    (
        "orchid-beta",
        BATCH,
        "running",
        {"step": 1200, "metrics": {"val_loss": 1.02, "best_val_loss": 0.97}},
    ),
    (
        "orchid-gamma",
        BATCH,
        "running",
        {"step": 400, "metrics": {"val_loss": 1.10, "best_val_loss": 1.05}},
    ),
    ("orchid-no-report", BATCH, "running", None),
    (
        "orchid-finished",
        BATCH,
        "succeeded",
        {"step": 1600, "metrics": {"val_loss": 0.40, "best_val_loss": 0.39}},
    ),
    (
        "other-slow",
        "other-tuning",
        "running",
        {"step": 1500, "metrics": {"val_loss": 1.25, "best_val_loss": 1.20}},
    ),
]


def seed(client, manifest, request):
    for index, (name, batch, state, progress) in enumerate(TRIALS):
        route = f"fit-{index}"
        task = client.submit_task(
            {"learning_rate": (index + 1) / 1000},
            name=name,
            metadata={"batch": batch},
            routes=[route],
        )
        run_id = "r_" + str(index).zfill(12)
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
                    {"run_id": run_id, "result": {"best_val_loss": 0.39}},
                )[0]
                == 204
            )


def check(client, manifest, request):
    current = client.list_tasks(limit=100).items
    assert len(current) == len(manifest["initial"])
    current_by_id = {task.id: task.model_dump(mode="json") for task in current}
    initial = manifest["initial"]

    selected_ids = [task_id for task_id, task in initial.items() if task["name"] == "orchid-beta"]
    assert len(selected_ids) == 1
    selected_id = selected_ids[0]
    before = initial[selected_id]
    after = current_by_id[selected_id]
    assert after["status"] == "cancelled"
    assert (
        after["progress"]
        == before["progress"]
        == {
            "step": 1200,
            "metrics": {"val_loss": 1.02, "best_val_loss": 0.97},
        }
    )
    assert after["progress_updated_at"] == before["progress_updated_at"]
    assert after["progress_attempt"] == before["progress_attempt"] == 1
    assert after["finished_at"] is not None
    for field in set(before) - {"status", "updated_at", "finished_at"}:
        assert after[field] == before[field]

    for task_id, snapshot in initial.items():
        if task_id != selected_id:
            assert current_by_id[task_id] == snapshot


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
