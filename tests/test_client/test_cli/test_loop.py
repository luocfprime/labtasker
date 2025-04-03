import os
import os.path as osp
import tempfile

import pytest
from rich.text import Text
from typer.testing import CliRunner

from labtasker.client.cli import app
from labtasker.client.core.api import create_queue, submit_task
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
                "arg5": 'He said: "What\'s the whether like today?"',
            },
        )


@pytest.fixture
def dummy_job_script_dir(proj_root):
    return osp.join(proj_root, "tests", "dummy_jobs")


class TestLoop:
    def test_loop_basic(self, setup_tasks, dummy_job_script_dir):
        script_path = osp.join(dummy_job_script_dir, "job_1.py")
        result = runner.invoke(
            app,
            [
                "loop",
                "-c",
                f"python {script_path} --arg1 %(arg1) --arg2 %(arg2) --arg5 %(arg5)",
            ],
        )
        assert result.exit_code == 0, result.output
        output_text = Text.from_ansi(result.output).plain
        for i in range(TOTAL_TASKS):
            assert f"Running task {i}" in output_text, output_text

    def test_loop_shell_functionality(self, setup_tasks, dummy_job_script_dir):
        if os.name == "nt":
            pytest.skip("Skipping shell test on Windows")

        # test execution with shell '&&'
        script_path = osp.join(dummy_job_script_dir, "job_1.py")
        random_str = "asjdfoiadlfg"
        result = runner.invoke(
            app,
            [
                "loop",
                "-c",
                f"python {script_path} --arg1 %(arg1) --arg2 %(arg2) --arg5 %(arg5) && echo '{random_str}'",
            ],
        )
        assert result.exit_code == 0, result.output
        output_text = Text.from_ansi(result.output).plain
        for i in range(TOTAL_TASKS):
            assert f"Running task {i}" in output_text, output_text
        assert random_str in output_text, output_text

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
                "--arg5",
                "%(arg5)",
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
                "--arg5=%(arg5)",
            ],
        )
        assert result.exit_code == 0, result.output
        output_text = Text.from_ansi(result.output).plain
        for i in range(TOTAL_TASKS):
            assert f"Running task {i}" in output_text, output_text

    @pytest.fixture
    def bash_script(self, dummy_job_script_dir):
        """Fixture to create a temporary bash script."""
        script_path = osp.join(dummy_job_script_dir, "job_1.py")

        bash_script_content = f"""#!/bin/bash
        arg1=%(arg1)
        arg2=%(arg2)
        arg5=%(arg5)

        python {script_path} --arg1 "$arg1" --arg2 "$arg2" --arg5 "$arg5"
        """

        # Create a temporary file for the script
        temp_file = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".sh")
        temp_file.write(bash_script_content)
        temp_file.close()

        # Make the script executable
        os.chmod(temp_file.name, 0o755)

        yield temp_file.name  # Return the path to the temporary script

        # Cleanup: Delete the temporary script after the test
        if os.path.exists(temp_file.name):
            os.remove(temp_file.name)

    def test_loop_script_path(self, setup_tasks, bash_script):
        if os.name == "nt":
            pytest.skip("Skipping shell test on Windows")

        result = runner.invoke(
            app,
            ["loop", "--executable", "/bin/bash", "--script-path", bash_script],
        )
        assert result.exit_code == 0, result.output
        output_text = Text.from_ansi(result.output).plain
        for i in range(TOTAL_TASKS):
            assert f"Running task {i}" in output_text, output_text
