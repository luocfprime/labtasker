import json
import runpy
from pathlib import Path


def seed(client, manifest, request):
    work = Path(manifest["work"])
    plan = {
        "prepare": {"args": {"dataset": "letters"}, "route": "prepare-v1"},
        "evaluate": {
            "args": {"dataset": "letters"},
            "seeds": [7, 11, 19],
            "route": "eval-v1",
        },
        "aggregate": {"args": {"report": "letters-summary"}, "route": "report-v1"},
    }
    (work / "pipeline.json").write_text(json.dumps(plan, indent=2))
    records = work / "experiments"
    records.mkdir()
    (records / "labtasker-routes.md").write_text(
        "# Approved pipeline configurations\n\n"
        "On the supplied Server, Queue default: prepare-v1 prepares letters; "
        "eval-v1 evaluates letters with the existing model and integer seed; "
        "report-v1 aggregates the existing evaluation outputs. "
        "Reuse of all three configurations is approved for this pipeline.\n"
    )


def check(client, manifest, request):
    current = client.list_tasks(limit=100).items
    assert len(current) == 5
    assert all(task.status == "pending" for task in current)
    preparation = [task for task in current if task.routes == ["prepare-v1"]]
    evaluations = [task for task in current if task.routes == ["eval-v1"]]
    reports = [task for task in current if task.routes == ["report-v1"]]
    assert len(preparation) == len(reports) == 1 and len(evaluations) == 3
    assert preparation[0].args == {"dataset": "letters"}
    assert preparation[0].dependencies == []
    assert sorted(task.args["seed"] for task in evaluations) == [7, 11, 19]
    for task in evaluations:
        assert task.args == {"dataset": "letters", "seed": task.args["seed"]}
        assert set(task.dependencies) == {preparation[0].id}
    assert reports[0].args == {"report": "letters-summary"}
    assert set(reports[0].dependencies) == {task.id for task in evaluations}


runpy.run_path(
    str(Path(__file__).parents[3] / "scenario.py"),
    run_name="__main__",
    init_globals={
        "CASE_ID": Path(__file__).parents[1].name,
        "EXAMINER_SEED": seed,
        "EXAMINER_CHECK": check,
    },
)
