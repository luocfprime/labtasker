from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from labtasker import Client


def test_python_and_bash_submission_loops(server_url: str) -> None:
    python_count = 50
    with Client(url=server_url, token="secret") as client:
        for index in range(python_count):
            task = client.submit_task(
                {"index": index, "enabled": index % 2 == 0},
                name=f"python-{index}",
                metadata={"source": "python", "batch": "common-usage"},
                routes=["batch-python"],
                task_id=f"t_PYTH{index:08d}",
            )
            assert task.status == "pending"
        assert client.count_tasks(filter='metadata.source == "python"') == python_count

    environment = dict(os.environ)
    environment.update(
        {
            "LABTASKER_URL": server_url,
            "LABTASKER_TOKEN": "secret",
            "LABTASKER_QUEUE": "default",
        }
    )
    function_count = 20
    function_script = """
import os
import labtasker

for index in range(int(os.environ["FUNCTION_COUNT"])):
    labtasker.submit_task(
        {"index": index, "enabled": False},
        name=f"function-{index}",
        metadata={"source": "function", "batch": "common-usage"},
        routes=["batch-function"],
        task_id=f"t_FUNC{index:08d}",
    )
"""
    environment["FUNCTION_COUNT"] = str(function_count)
    function_result = subprocess.run(
        [sys.executable, "-c", function_script],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert function_result.returncode == 0, function_result.stderr
    assert function_result.stdout == ""

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for the shell submission-loop coverage.")
    bash_count = 10
    script = r"""
set -euo pipefail
for ((index = 0; index < BASH_COUNT; index++)); do
  printf -v task_id 't_BASH%08d' "$index"
  printf -v args '{"index":%d,"enabled":true}' "$index"
  "$PYTHON_EXECUTABLE" -m labtasker task submit \
    --id "$task_id" \
    --name "bash-$index" \
    --args "$args" \
    --metadata '{"source":"bash","batch":"common-usage"}' \
    --route batch-bash \
    >/dev/null
done
"""
    environment.update(
        {
            "BASH_COUNT": str(bash_count),
            "PYTHON_EXECUTABLE": sys.executable,
            "LABTASKER_URL": server_url,
            "LABTASKER_TOKEN": "secret",
            "LABTASKER_QUEUE": "default",
        }
    )
    result = subprocess.run(
        [bash, "-c", script],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""

    with Client(url=server_url, token="secret") as client:
        assert client.count_tasks(filter='metadata.source == "bash"') == bash_count
        assert client.count_tasks(filter='metadata.source == "function"') == function_count
        page = client.list_tasks(filter='metadata.batch == "common-usage"', limit=17)
        tasks = list(page.items)
        while page.next_cursor is not None:
            page = client.list_tasks(
                filter='metadata.batch == "common-usage"',
                limit=17,
                cursor=page.next_cursor,
            )
            tasks.extend(page.items)

    assert len(tasks) == python_count + function_count + bash_count
    assert len({task.id for task in tasks}) == len(tasks)
    assert {task.routes[0] for task in tasks} == {
        "batch-python",
        "batch-function",
        "batch-bash",
    }
    assert {task.args["index"] for task in tasks if task.metadata["source"] == "python"} == set(
        range(python_count)
    )
    assert {task.args["index"] for task in tasks if task.metadata["source"] == "bash"} == set(
        range(bash_count)
    )
    assert {task.args["index"] for task in tasks if task.metadata["source"] == "function"} == set(
        range(function_count)
    )
