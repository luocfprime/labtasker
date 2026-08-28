from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from labtasker import Client

ROOT = Path(__file__).resolve().parents[2]


def documented_block(path: Path, language: str, contains: str) -> str:
    pattern = re.compile(rf"^```{language}(?:[^\n]*)\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)
    matches = [match.group(1) for match in pattern.finditer(path.read_text(encoding="utf-8"))]
    selected = [block for block in matches if contains in block]
    assert len(selected) == 1, (path, language, contains)
    return selected[0]


@pytest.mark.skipif(os.name != "posix", reason="The documented Command Worker requires POSIX")
def test_tutorial_and_skill_quickstart_recipe(server_url: str, tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to execute the documented shell recipe.")

    tutorial = ROOT / "docs/getting-started.md"
    skill = ROOT / "skills/labtasker/SKILL.md"
    evaluator = documented_block(tutorial, "python", 'parser.add_argument("--prediction"')
    submit = documented_block(skill, "bash", "--name sample-1")
    worker_command = documented_block(skill, "bash", "CUDA_VISIBLE_DEVICES=0")
    list_command = documented_block(tutorial, "bash", "task list --status succeeded")
    (tmp_path / "evaluate.py").write_text(evaluator, encoding="utf-8")

    environment = dict(os.environ)
    environment.update(
        {
            "PATH": f"{Path(sys.executable).parent}{os.pathsep}{environment['PATH']}",
            "LABTASKER_URL": server_url,
            "LABTASKER_TOKEN": "secret",
            "LABTASKER_QUEUE": "default",
        }
    )
    submitted = subprocess.run(
        [bash, "-c", submit],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert submitted.returncode == 0, submitted.stderr
    task_id = json.loads(submitted.stdout)["id"]

    worker = subprocess.Popen(
        [bash, "-c", worker_command],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        with Client(url=server_url, token="secret") as client:
            while time.monotonic() < deadline:
                task = client.get_task(task_id)
                if task.status == "succeeded":
                    break
                assert worker.poll() is None
                time.sleep(0.05)
            else:
                pytest.fail("The documented Worker did not finish its Task.")
        assert task.result == {"score": 1.0}
    finally:
        if worker.poll() is None:
            os.killpg(worker.pid, signal.SIGINT)
        try:
            stdout, stderr = worker.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(worker.pid, signal.SIGKILL)
            stdout, stderr = worker.communicate(timeout=5)
            pytest.fail(f"The documented Worker did not stop. stdout={stdout!r} stderr={stderr!r}")
        assert stdout == ""
        assert "Traceback" not in stderr

    listed = subprocess.run(
        [bash, "-c", list_command],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert listed.returncode == 0, listed.stderr
    page = json.loads(listed.stdout)
    assert [item["id"] for item in page["items"]] == [task_id]

    fetched = subprocess.run(
        [sys.executable, "-m", "labtasker", "task", "get", task_id],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert fetched.returncode == 0, fetched.stderr
    assert json.loads(fetched.stdout)["result"] == {"score": 1.0}
