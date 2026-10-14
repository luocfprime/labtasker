import json
import runpy
from pathlib import Path


def seed(client, manifest, request):
    required = client.submit_task({}, name="required-input", routes=["input-v1"])
    run_id = "r_RepairHold01"
    assert (
        request(
            manifest["url"],
            "/api/v2/queues/default/tasks/claim",
            manifest["token"],
            {"route": "input-v1", "run_id": run_id},
        )[0]
        == 200
    )
    assert (
        request(
            manifest["url"],
            f"/api/v2/queues/default/tasks/{required.id}/complete",
            manifest["token"],
            {"run_id": run_id, "result": {"score": 1}},
        )[0]
        == 204
    )
    draft = client.submit_task({}, name="optional-draft", routes=["draft-v1"])
    main = client.submit_task(
        {}, name="report-main", routes=["report-v1"], dependencies=[required.id, draft.id]
    )
    other = client.submit_task(
        {}, name="unrelated-report", routes=["report-v1"], dependencies=[draft.id]
    )
    manifest["roles"] = {
        "required": required.id,
        "draft": draft.id,
        "main": main.id,
        "other": other.id,
    }
    (Path(manifest["work"]) / "project.json").write_text(
        json.dumps(
            {"required_input": required.id, "optional_draft": draft.id, "report_main": main.id},
            indent=2,
        )
    )


def check(client, manifest, request):
    current = {task.id: task.model_dump(mode="json") for task in client.list_tasks(limit=100).items}
    roles = manifest["roles"]
    assert set(current) == set(manifest["initial"]) - {roles["draft"]}
    assert current[roles["main"]]["dependencies"] == [roles["required"]]
    assert current[roles["main"]]["status"] == "pending"
    before_main = manifest["initial"][roles["main"]]
    for key in before_main.keys() - {"dependencies", "updated_at"}:
        assert current[roles["main"]][key] == before_main[key]
    for role in ["required", "other"]:
        assert current[roles[role]] == manifest["initial"][roles[role]]


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
