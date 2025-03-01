import os.path as osp

import pytest
from rich.text import Text
from typer.testing import CliRunner

from labtasker import create_queue, submit_task
from labtasker.client.cli import app
from labtasker.client.core.context import set_current_worker_id
from tests.fixtures.logging import silence_logger

runner = CliRunner()

pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
]

TOTAL_TASKS = 5


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


@pytest.fixture
def setup_tasks(db_fixture):
    # relies on db_fixture to clear db after each test case
    for i in range(TOTAL_TASKS):
        submit_task(
            task_name=f"test_task_{i}",
            args={
                "arg1": i,
                "arg2": {"arg3": i, "arg4": "foo"},
            },
        )


@pytest.fixture(autouse=True)
def reset_worker_id():
    set_current_worker_id(None)


@pytest.fixture
def dummy_job_script_dir(proj_root):
    return osp.join(proj_root, "tests", "dummy_jobs")


class TestLoop:
    def test_loop_basic(self, setup_tasks, dummy_job_script_dir):
        script_path = osp.join(dummy_job_script_dir, "job_1.py")
        result = runner.invoke(
            app,
            ["loop", "-c", f"python {script_path} --arg1 %(arg1) --arg2 %(arg2)"],
        )
        assert result.exit_code == 0, result.output
        output_text = Text.from_ansi(result.output).plain
        for i in range(TOTAL_TASKS):
            assert f"Running task {i}" in output_text, output_text

    def test_loop_positional_arg(self, setup_tasks, dummy_job_script_dir):
        script_path = osp.join(dummy_job_script_dir, "job_1.py")
        result = runner.invoke(
            app,
            [
                "loop",
                "--",
                "python",
                script_path,
                "--arg1",
                "%(arg1)",
                "--arg2",
                "%(arg2)",
            ],
        )
        assert result.exit_code == 0, result.output
        output_text = Text.from_ansi(result.output).plain
        for i in range(TOTAL_TASKS):
            assert f"Running task {i}" in output_text, output_text

    def test_loop_positional_arg_equal_options(self, setup_tasks, dummy_job_script_dir):
        script_path = osp.join(dummy_job_script_dir, "job_1.py")
        result = runner.invoke(
            app,
            [
                "loop",
                "--",
                "python",
                script_path,
                "--arg1=%(arg1)",
                "--arg2=%(arg2)",
            ],
        )
        assert result.exit_code == 0, result.output
        output_text = Text.from_ansi(result.output).plain
        for i in range(TOTAL_TASKS):
            assert f"Running task {i}" in output_text, output_text
