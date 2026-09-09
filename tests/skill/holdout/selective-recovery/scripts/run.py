import runpy
from pathlib import Path


def seed(client, manifest, request):
    for batch, value, state in [
        ("winter", 1, "failed"),
        ("winter", 2, "failed"),
        ("winter", 3, "failed"),
        ("winter", 4, "succeeded"),
        ("other", 2, "failed"),
    ]:
        route = f"eval-{batch}-{value}"
        t = client.submit_task(
            {"dataset": batch, "seed": value},
            name=route,
            metadata={"batch": batch},
            routes=[route],
            max_attempts=1,
        )
        run = "r_" + (batch + str(value)).ljust(12, "x")
        assert (
            request(
                manifest["url"],
                "/api/v2/queues/default/tasks/claim",
                manifest["token"],
                {"route": route, "run_id": run},
            )[0]
            == 200
        )
        verb = "complete" if state == "succeeded" else "fail"
        body = (
            {"run_id": run, "result": {"score": value}}
            if state == "succeeded"
            else {
                "run_id": run,
                "error": {"type": "ValueError", "message": "Input missing", "traceback": None},
            }
        )
        assert (
            request(
                manifest["url"],
                f"/api/v2/queues/default/tasks/{t.id}/{verb}",
                manifest["token"],
                body,
            )[0]
            == 204
        )


def check(client, manifest, request):
    current = client.list_tasks().items
    by_id = {t.id: t.model_dump(mode="json") for t in current}
    for tid, old in manifest["initial"].items():
        if old["args"]["dataset"] == "winter" and old["args"]["seed"] in {2, 3}:
            assert len([t for t in current if t.args == old["args"] and t.status == "pending"]) == 1
        else:
            assert by_id[tid] == old
    assert not any(t.status == "running" for t in current)


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
