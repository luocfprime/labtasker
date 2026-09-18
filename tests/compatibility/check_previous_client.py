"""Run a published v2 Client against the current Server over real HTTP.

Run explicitly with uv; this gate installs the pinned published Client into an
isolated environment and is intentionally outside the ordinary pytest suite.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def check_client(url: str, version: str) -> None:
    from labtasker import Client

    assert importlib.metadata.version("labtasker-client") == version
    with Client(url=url, token="compatibility-test") as client:
        task = client.submit_task({"seed": 7}, routes=["compatibility"], max_attempts=1)
        assert client.get_task(task.id).args == {"seed": 7}
        assert [item.id for item in client.list_tasks().items] == [task.id]
        run_id = "r_COMPAT000001"
        claim = client._claim(route="compatibility", run_id=run_id)
        assert claim is not None and claim.task.id == task.id
        client._heartbeat(task_id=task.id, run_id=run_id)
        client._complete(task_id=task.id, run_id=run_id, result={"score": 0.9})
        finished = client.get_task(task.id)
        assert finished.status == "succeeded" and finished.result == {"score": 0.9}
        failed = client.submit_task({}, routes=["compatibility"], max_attempts=1)
        failure_run_id = "r_COMPAT000002"
        claim = client._claim(route="compatibility", run_id=failure_run_id)
        assert claim is not None and claim.task.id == failed.id
        client._fail(
            task_id=failed.id,
            run_id=failure_run_id,
            error_type="ExpectedError",
            message="compatibility failure report",
            traceback=None,
        )
        assert client.get_task(failed.id).status == "failed"
        assert client._claim(route="compatibility", run_id="r_COMPAT000003") is None
    print(f"Published Client {version}: submit/get/list/claim/heartbeat/complete/fail passed")


def run_gate(version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="labtasker-compatibility-") as directory:
        root = Path(directory)
        environment = root / "client"
        subprocess.run(["uv", "venv", "--python", sys.executable, str(environment)], check=True)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run(
            ["uv", "pip", "install", "--python", str(python), f"labtasker-client=={version}"],
            check=True,
        )
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        env = {**os.environ, "LABTASKER_SERVER_TOKEN": "compatibility-test"}
        # Do not let an inherited source path shadow the installed old Client.
        client_env = {
            key: value
            for key, value in env.items()
            if key != "PYTHONPATH" and key.lower() not in {"http_proxy", "https_proxy", "all_proxy"}
        }
        with (root / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "labtasker_server",
                    "serve",
                    "--connection",
                    "http",
                    "--port",
                    str(port),
                    "--database",
                    str(root / "server.db"),
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise RuntimeError(f"Server failed to become ready:\n{log.read()}")
                    try:
                        request = Request(
                            f"{url}/health",
                            headers={"Authorization": "Bearer compatibility-test"},
                        )
                        with urlopen(request, timeout=1) as response:
                            assert response.status == 200
                        break
                    except (URLError, TimeoutError):
                        time.sleep(0.1)
                subprocess.run(
                    [
                        str(python),
                        str(Path(__file__).resolve()),
                        "--client-version",
                        version,
                        "--url",
                        url,
                    ],
                    env=client_env,
                    cwd=root,
                    check=True,
                    timeout=60,
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client-version", required=True)
    parser.add_argument("--url", help="Run only the isolated Client checks against this URL")
    args = parser.parse_args()
    if args.url:
        check_client(args.url, args.client_version)
    else:
        run_gate(args.client_version)
