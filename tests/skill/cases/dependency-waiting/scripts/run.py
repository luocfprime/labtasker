import runpy
import secrets
from pathlib import Path


def seed(client, manifest, request):
    good = client.submit_task({}, name="prepared-input", routes=["prepare-v1"])
    bad = client.submit_task({}, name="failed-evaluation", routes=["eval-v1"], max_attempts=1)
    for task, route, verb, extra in [
        (good, "prepare-v1", "complete", {"result": {"path": "prepared.json"}}),
        (
            bad,
            "eval-v1",
            "fail",
            {"error": {"type": "ValueError", "message": "Bad input", "traceback": None}},
        ),
    ]:
        run_id = "r_" + secrets.token_urlsafe(9)
        assert (
            request(
                manifest["url"],
                "/api/v2/queues/default/tasks/claim",
                manifest["token"],
                {"route": route, "run_id": run_id},
            )[0]
            == 200
        )
        assert (
            request(
                manifest["url"],
                f"/api/v2/queues/default/tasks/{task.id}/{verb}",
                manifest["token"],
                {"run_id": run_id, **extra},
            )[0]
            == 204
        )
    client.submit_task(
        {},
        name="atlas-report",
        routes=["report-v1"],
        metadata={"batch": "atlas"},
        dependencies=[good.id, bad.id],
    )
    client.submit_task(
        {},
        name="atlas-extra",
        routes=["report-v1"],
        metadata={"batch": "atlas"},
        dependencies=["t_MissingInput"],
    )


def check(client, manifest, request):
    current = {task.id: task.model_dump(mode="json") for task in client.list_tasks(limit=100).items}
    assert current == manifest["initial"]


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
