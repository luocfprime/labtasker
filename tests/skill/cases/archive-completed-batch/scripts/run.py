import runpy
from pathlib import Path


def all_tasks(client):
    out = []
    cursor = None
    while True:
        page = client.list_tasks(include_archived=True, limit=100, cursor=cursor)
        out.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return out


def seed(client, manifest, request):
    entries = [
        ("quartz", "succeeded", False),
        ("quartz", "failed", False),
        ("quartz", "cancelled", False),
        ("quartz", "pending", False),
        ("quartz", "running", False),
        ("quartz", "succeeded", True),
        ("cedar", "failed", False),
        ("cedar", "succeeded", True),
    ]
    for index, (batch, state, archived) in enumerate(entries):
        route = f"archive-eval-{index}"
        t = client.submit_task(
            {"seed": index}, name=route, metadata={"batch": batch}, routes=[route], max_attempts=1
        )
        if state == "cancelled":
            client.cancel_task(t.id)
        elif state in {"running", "succeeded", "failed"}:
            run = "r_" + str(index).zfill(12)
            assert (
                request(
                    manifest["url"],
                    "/api/v2/queues/default/tasks/claim",
                    manifest["token"],
                    {"route": route, "run_id": run},
                )[0]
                == 200
            )
            if state != "running":
                verb = "complete" if state == "succeeded" else "fail"
                body = (
                    {"run_id": run, "result": {"score": index / 10}}
                    if state == "succeeded"
                    else {
                        "run_id": run,
                        "error": {
                            "type": "ValueError",
                            "message": "input unavailable",
                            "traceback": None,
                        },
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
        assert client.get_task(t.id).status == state
        if archived:
            client.update_task(t.id, {"archived": True})
    manifest["all_initial"] = {t.id: t.model_dump(mode="json") for t in all_tasks(client)}


def check(client, manifest, request):
    before = manifest["all_initial"]
    after = {t.id: t.model_dump(mode="json") for t in all_tasks(client)}
    assert set(after) == set(before)
    for tid, old in before.items():
        selected = old["metadata"]["batch"] == "quartz" and old["status"] in {
            "succeeded",
            "failed",
            "cancelled",
        }
        if selected and not old["archived"]:
            assert after[tid]["archived"] is True
            for field in set(old) - {"archived", "updated_at"}:
                assert after[tid][field] == old[field], (tid, field)
        else:
            assert after[tid] == old


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
