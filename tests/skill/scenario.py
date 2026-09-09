"""Small executable examiner fixtures; never provided to candidates.

Invoke a case's scripts/run.py with setup, check MANIFEST, or cleanup MANIFEST.
All state and processes are dedicated to a temporary run. No pytest collection.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from labtasker import Client


def request(url, path, token, body=None, method=None):
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def clean_env():
    return {k: v for k, v in os.environ.items() if not k.startswith("LABTASKER_")}


def tasks(client):
    result = []
    cursor = None
    while True:
        page = client.list_tasks(limit=100, cursor=cursor)
        result.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            return result


def setup(case):
    if platform.system() not in {
        "Linux",
        "Darwin",
    }:
        print(
            json.dumps({"status": "unexecuted", "reason": "Linux or macOS fixture host required"})
        )
        return
    root = Path(tempfile.mkdtemp(prefix=f"labtasker-skill-{case}-"))
    work = root / "work"
    work.mkdir()
    token = secrets.token_urlsafe(24)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = clean_env() | {"LABTASKER_SERVER_TOKEN": token}
    log = root / "server.log"
    manifest = dict(
        case=case,
        root=str(root),
        work=str(work),
        url=url,
        token=token,
        python=sys.executable,
        owner=secrets.token_hex(12),
    )
    path = root / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2))
    try:
        if platform.system() == "Darwin":
            image = os.environ.get("LABTASKER_SKILL_IMAGE", "labtasker-skill-current")
            name = "labtasker-skill-" + manifest["owner"]
            manifest["container"] = name
            path.write_text(json.dumps(manifest, indent=2))
            launched = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--user",
                    "0",
                    "--name",
                    name,
                    "-p",
                    f"127.0.0.1:{port}:8000",
                    "-e",
                    "LABTASKER_SERVER_TOKEN=" + token,
                    image,
                    "--host",
                    "0.0.0.0",
                    "--port",
                    "8000",
                    "--database",
                    "/run/server.db",
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            manifest["container"] = launched.stdout.strip()
            manifest["image"] = subprocess.check_output(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True
            ).strip()
            process = None
        else:
            with log.open("w") as output:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "labtasker_server",
                        "serve",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--database",
                        str(root / "server.db"),
                    ],
                    cwd=work,
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            manifest["pid"] = process.pid
        path.write_text(json.dumps(manifest, indent=2))
        for _ in range(100):
            if process is None:
                state = subprocess.check_output(
                    ["docker", "inspect", manifest["container"], "--format", "{{.State.Running}}"],
                    text=True,
                ).strip()
                if state != "true":
                    raise RuntimeError(
                        subprocess.run(
                            ["docker", "logs", manifest["container"]],
                            capture_output=True,
                            text=True,
                        ).stderr
                    )
            if process is not None and process.poll() is not None:
                raise RuntimeError(log.read_text())
            try:
                if request(url, "/health", token)[0] == 200:
                    break
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("dedicated Server did not become healthy")
        assert request(url, "/api/v2/queues", "wrong-token")[0] == 401
        with Client(url=url, token=token) as client:
            client.create_queue("default")
            client.create_queue("owner-" + manifest["owner"])
            seed(case, client, manifest)
        path.write_text(json.dumps(manifest, indent=2))
        connection = dict(
            url=url, token=token, queue="default", work=str(work), python=sys.executable
        )
        (work / "connection.json").write_text(json.dumps(connection, indent=2))
        if "container" in manifest:
            manifest["execution_class"] = "diagnostic: image provenance requires verification"
            manifest["server_pydantic"] = subprocess.check_output(
                [
                    "docker",
                    "exec",
                    manifest["container"],
                    "python",
                    "-c",
                    "import importlib.metadata; print(importlib.metadata.version('pydantic'))",
                ],
                text=True,
            ).strip()
        else:
            manifest["execution_class"] = "native workspace"
        path.write_text(json.dumps(manifest, indent=2))
        print(
            json.dumps(
                dict(manifest=str(path), execution_class=manifest["execution_class"], **connection)
            )
        )
    except BaseException:
        cleanup(manifest)
        raise


def seed(case, client, manifest):
    work = Path(manifest["work"])
    plans = [
        {"dataset": dataset, "seed": seed}
        for dataset in ["small-a", "small-b"]
        for seed in [1, 2, 3]
    ]
    if case in {"submit-sweep", "run-existing-evaluator"}:
        (work / "cases.json").write_text(json.dumps(plans, indent=2))
        route = "eval-v1" if case == "submit-sweep" else "score-v1"
        write_route(
            work, route, "scorer.py; same fixed evaluator revision; dataset and integer seed vary"
        )
        if case == "run-existing-evaluator":
            (work / "scorer.py").write_text(SCORER)
    elif case == "progress-summary":
        for index in range(180):
            state = (
                "succeeded"
                if index < 139
                else "pending"
                if index < 170
                else "failed"
                if index < 177
                else "cancelled"
            )
            seeded_task(
                client,
                manifest,
                f"autumn-{index:03}",
                {"dataset": "bench", "seed": index},
                "autumn",
                state,
            )
        for index in range(4):
            seeded_task(
                client,
                manifest,
                f"other-{index}",
                {"dataset": "other", "seed": index},
                "other",
                "pending",
            )
    elif case == "waiting-diagnosis":
        for index in range(4):
            client.submit_task(
                {"dataset": "bench", "seed": index}, name=f"new-eval-{index}", routes=["judge-v2"]
            )
        write_route(
            work, "judge-v1", "old checkpoint v1, old score schema; incompatible with v2 outputs"
        )
        with (work / "experiments" / "labtasker-routes.md").open("a") as f:
            f.write(
                "\n# judge-v2\nNew checkpoint v2 and new score schema; "
                "current batch requires these outputs.\n"
            )
        wid = "w_StudyWorker1"
        code, _ = request(
            manifest["url"],
            "/api/v2/queues/default/workers/" + wid,
            manifest["token"],
            {"route": "judge-v1", "status": "idle", "task_id": None},
            "PUT",
        )
        assert code == 204
    elif case == "recover-selected-batch":
        for index, state in enumerate(["failed", "cancelled", "succeeded", "pending"]):
            seeded_task(
                client,
                manifest,
                f"autumn-{index}",
                {"dataset": "bench", "seed": index},
                "autumn",
                state,
            )
        seeded_task(
            client, manifest, "other-failed", {"dataset": "other", "seed": 9}, "other", "failed"
        )
    elif case == "connect-project":
        client.create_queue("research")
        config = work / ".labtasker" / "config.toml"
        config.parent.mkdir()
        config.write_text('url = "http://127.0.0.1:1"\nqueue = "wrong"\n')
        (work / "existing.py").write_text(
            "from labtasker import Client\nwith Client() as c:\n"
            '    t = c.submit_task({"dataset": "connection-smoke", "seed": 9},\n'
            '                      routes=["eval-v1"])\n'
            "    print(t.id)\n"
        )
    elif "EXAMINER_SEED" in globals():
        globals()["EXAMINER_SEED"](client, manifest, request)
    else:
        raise ValueError(case)
    manifest["initial"] = {t.id: t.model_dump(mode="json") for t in tasks(client)}


SCORER = r'''"""Existing standalone evaluator; values stand in for an expensive loaded model."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).parent

def audit(value):
    with (ROOT / "evaluation-audit.jsonl").open("a") as f:
        f.write(json.dumps(value) + "\n")

class Scorer:
    def __init__(self):
        audit({"event": "load"})

    def evaluate(self, dataset, seed):
        audit({"event": "evaluate", "dataset": dataset, "seed": seed})
        return {"dataset": dataset, "seed": seed, "score": len(dataset) + seed / 10}

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    Path(a.output).write_text(json.dumps(Scorer().evaluate(a.dataset, a.seed)))
'''


def write_route(work, route, details):
    path = work / "experiments" / "labtasker-routes.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        f"# {route}\n\nQueue default on the provided Server. {details}.\n"
        "First submitted 2026-09-08 +08:00. Reuse approved for the current batch.\n"
    )


def seeded_task(client, manifest, name, args, batch, state):
    route = "eval-" + name
    task = client.submit_task(
        args, name=name, routes=[route], metadata={"batch": batch}, max_attempts=1
    )
    if state == "cancelled":
        client.cancel_task(task.id)
    elif state in {"succeeded", "failed"}:
        run = "r_" + secrets.token_urlsafe(9)
        code, _ = request(
            manifest["url"],
            "/api/v2/queues/default/tasks/claim",
            manifest["token"],
            {"route": route, "run_id": run},
        )
        assert code == 200
        verb = "complete" if state == "succeeded" else "fail"
        body = (
            {"run_id": run, "result": {"score": args["seed"]}}
            if state == "succeeded"
            else {
                "run_id": run,
                "error": {
                    "type": "ValueError",
                    "message": "Input shard unavailable",
                    "traceback": None,
                },
            }
        )
        code, _ = request(
            manifest["url"],
            f"/api/v2/queues/default/tasks/{task.id}/{verb}",
            manifest["token"],
            body,
        )
        assert code == 204
    return task


def verify_owner(manifest):
    root = Path(manifest["root"])
    assert root.name.startswith("labtasker-skill-") and Path(manifest["work"]).parent == root
    with Client(url=manifest["url"], token=manifest["token"]) as client:
        assert "owner-" + manifest["owner"] in {q.name for q in client.list_queues()}


def check(manifest):
    verify_owner(manifest)
    work = Path(manifest["work"])
    case = manifest["case"]
    with Client(url=manifest["url"], token=manifest["token"]) as client:
        current = tasks(client)
        snapshot = {t.id: t.model_dump(mode="json") for t in current}
        if case == "submit-sweep":
            assert len(current) == 6 and all(t.status == "pending" for t in current)
            assert all("eval-v1" in t.routes for t in current)
            # Input interpretation/replay script is reviewed independently; no private args schema.
        elif case == "run-existing-evaluator":
            assert current and all(t.status == "succeeded" for t in current)
            events = [
                json.loads(line)
                for line in (work / "evaluation-audit.jsonl").read_text().splitlines()
            ]
            assert sum(e["event"] == "load" for e in events) == 1
            evaluated = [(e["dataset"], e["seed"]) for e in events if e["event"] == "evaluate"]
            assert sorted(evaluated) == sorted(
                (d, s) for d in ["small-a", "small-b"] for s in [1, 2, 3]
            )
            # Examiner verifies numerical results in the candidate's chosen artifact layout.
        elif case in {"progress-summary", "waiting-diagnosis"}:
            assert snapshot == manifest["initial"]
        elif case == "recover-selected-batch":
            old = manifest["initial"]
            for tid, before in old.items():
                selected = before["metadata"].get("batch") == "autumn" and before["status"] in {
                    "failed",
                    "cancelled",
                }
                if not selected:
                    assert snapshot[tid] == before
                else:
                    ready = [
                        t for t in current if t.args == before["args"] and t.status == "pending"
                    ]
                    assert len(ready) == 1
            selected_args = [
                t["args"]
                for t in old.values()
                if t["metadata"].get("batch") == "autumn" and t["status"] in {"failed", "cancelled"}
            ]
            assert all(t.args in selected_args for t in current if t.id not in old)
            assert not any(t.status == "running" for t in current)
        elif case == "connect-project":
            research = client.list_tasks(queue="research").items
            assert len(research) == 1 and research[0].args == {
                "dataset": "connection-smoke",
                "seed": 9,
            }
            assert current == []
            env = clean_env() | {"LABTASKER_TOKEN": manifest["token"]}
            result = subprocess.run(
                [sys.executable, "-m", "labtasker", "config", "show"],
                cwd=work,
                env=env,
                text=True,
                capture_output=True,
                check=True,
            )
            selected = json.loads(result.stdout)
            assert selected["url"] == manifest["url"] and selected["queue"] == "research"
        elif "EXAMINER_CHECK" in globals():
            globals()["EXAMINER_CHECK"](client, manifest, request)
        else:
            raise ValueError(case)
    print(
        json.dumps(
            {
                "state_checks": "passed",
                "workflow": "examiner interpretation/evidence review required",
            }
        )
    )


def stop_owned_process(pid, markers):
    """Stop only a matching session leader; tolerate already exited children."""

    def matches():
        found = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="], text=True, capture_output=True
        ).stdout
        try:
            return all(marker in found for marker in markers) and os.getpgid(pid) == pid
        except ProcessLookupError:
            return False

    if not matches():
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not matches():
            return
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    return
            except ChildProcessError:
                pass
            if not matches():
                return
            time.sleep(0.05)
    raise RuntimeError(f"Owned process {pid} did not stop")


def cleanup(manifest):
    root = Path(manifest["root"])
    assert root.name.startswith("labtasker-skill-")
    if "container" in manifest:
        container = manifest["container"]
        found = subprocess.run(
            ["docker", "inspect", container, "--format", "{{.Name}}"],
            text=True,
            capture_output=True,
        )
        if found.returncode == 0:
            assert found.stdout.strip() == "/labtasker-skill-" + manifest["owner"]
            subprocess.run(
                ["docker", "stop", "-t", "3", container], capture_output=True, check=True
            )
            logs = subprocess.run(["docker", "logs", container], text=True, capture_output=True)
            (root / "server.log").write_text(logs.stdout + logs.stderr)
            subprocess.run(
                ["docker", "cp", container + ":/run/server.db", str(root / "server.db")],
                capture_output=True,
            )
            subprocess.run(["docker", "rm", container], capture_output=True, check=True)
        print(json.dumps({"cleanup": "completed", "artifacts": str(root)}))
        return
    if "pid" in manifest:
        stop_owned_process(manifest["pid"], [str(root / "server.db"), "labtasker_server"])
    print(json.dumps({"cleanup": "completed", "artifacts": str(root)}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["setup", "check", "cleanup"])
    parser.add_argument("manifest", nargs="?")
    args = parser.parse_args()
    case = Path(sys.argv[0]).parents[1].name
    # runpy changes argv[0]; the wrapper passes its own path through an environment-free global.
    case = globals().get("CASE_ID", case)
    if args.action == "setup":
        setup(case)
    else:
        manifest = json.loads(Path(args.manifest).read_text())
        (check if args.action == "check" else cleanup)(manifest)


if __name__ == "__main__":
    main()
