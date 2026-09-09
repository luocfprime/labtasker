import runpy
from pathlib import Path


def seed(client, manifest, request):
    for value in range(12):
        route = f"summer-{value}"
        t = client.submit_task(
            {"seed": value}, name=route, metadata={"batch": "summer"}, routes=[route]
        )
        run = "r_" + str(value).zfill(12)
        assert (
            request(
                manifest["url"],
                "/api/v2/queues/default/tasks/claim",
                manifest["token"],
                {"route": route, "run_id": run},
            )[0]
            == 200
        )
        assert (
            request(
                manifest["url"],
                f"/api/v2/queues/default/tasks/{t.id}/complete",
                manifest["token"],
                {"run_id": run, "result": {"score": value / 12}},
            )[0]
            == 204
        )
    client.submit_task({"seed": 99}, name="other", metadata={"batch": "other"})
    assert (
        request(
            manifest["url"],
            "/api/v2/queues/default/workers/w_TransferWork",
            manifest["token"],
            {"route": "summer-11", "status": "busy", "task_id": t.id},
            "PUT",
        )[0]
        == 204
    )


def check(client, manifest, request):
    assert {t.id: t.model_dump(mode="json") for t in client.list_tasks().items} == manifest[
        "initial"
    ]


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
