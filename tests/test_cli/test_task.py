from ast import literal_eval

import pytest
from typer.testing import CliRunner

from labtasker.client.cli import app
from tests.test_cli.test_queue import cli_create_queue_from_config

runner = CliRunner()

# Mark the entire file as e2e, integration and unit tests
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.integration,
    pytest.mark.unit,
    pytest.mark.dependency(
        depends=["tests/test_cli/test_queue.py::TestCreate::test_create_no_metadata"],
        scope="session",
    ),
]


class TestSubmit:
    def test_submit_task(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "task",
                "submit",
                "--task-name",
                "new-test-task",
                "--args",
                '{"key": "value"}',
                "--metadata",
                '{"tag": "test"}',
                "--cmd",
                "echo hello",
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify task is created
        task = db_fixture._tasks.find_one({"task_name": "new-test-task"})
        assert task is not None
        assert task["args"] == {"key": "value"}
        assert task["metadata"] == literal_eval('{"tag": "test"}')

    def test_submit_task_no_metadata(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "task",
                "submit",
                "--task-name",
                "new-test-task-no-metadata",
                "--args",
                '{"key": "value"}',
                "--cmd",
                "echo hello",
            ],
        )
        assert result.exit_code == 0, result.output

        task = db_fixture._tasks.find_one({"task_name": "new-test-task-no-metadata"})
        assert task is not None
        assert task["args"] == {"key": "value"}
        assert task["metadata"] == {}


@pytest.fixture
def setup_pending_task(db_fixture, cli_create_queue_from_config):
    """Setup a task in PENDING state in current queue."""
    queue_id = db_fixture._queues.find_one(
        {"queue_name": cli_create_queue_from_config.queue_name}
    )["_id"]
    task_id = db_fixture.create_task(
        queue_id=queue_id,
        task_name="test-task",
        args={"key": "value"},
        metadata={"tag": "test"},
        cmd="echo hello",
        heartbeat_timeout=60,
        task_timeout=300,
        max_retries=3,
    )
    return task_id


@pytest.fixture
def setup_running_task(db_fixture, cli_create_queue_from_config):
    """Setup a task in RUNNING state in current queue."""
    queue_id = db_fixture._queues.find_one(
        {"queue_name": cli_create_queue_from_config.queue_name}
    )["_id"]
    task_id = db_fixture.create_task(
        queue_id=queue_id,
        task_name="test-task",
        args={"key": "value"},
        metadata={"tag": "test"},
        cmd="echo hello",
        heartbeat_timeout=60,
        task_timeout=300,
        max_retries=3,
    )
    db_fixture.fetch_task(queue_id=queue_id)  # PENDING -> RUNNING
    return task_id


class TestReport:
    def test_report_task_status(self, db_fixture, setup_running_task):
        task_id = setup_running_task
        result = runner.invoke(app, ["task", "report", task_id, "success"])
        assert result.exit_code == 0, result.output

        # Verify task status is updated
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task is not None
        assert task["status"] == "success"


class TestLs:
    @pytest.fixture
    def setup_tasks(self, db_fixture, cli_create_queue_from_config):
        queue_id = db_fixture._queues.find_one(
            {"queue_name": cli_create_queue_from_config.queue_name}
        )["_id"]
        # Create multiple tasks for testing
        for i in range(5):
            db_fixture.create_task(
                queue_id=queue_id,
                task_name=f"task-{i}",
                args={"key": f"value-{i}"},
                metadata={"tag": f"test-{i}"},
                cmd="echo hello",
            )

    def test_ls_tasks(self, db_fixture, setup_tasks):
        result = runner.invoke(app, ["task", "ls"])
        assert result.exit_code == 0, result.output

        # Check that the output contains the created tasks
        for i in range(5):
            assert f"task-{i}" in result.output

    def test_ls_tasks_with_filter(self, db_fixture, setup_tasks):
        result = runner.invoke(app, ["task", "ls", "--task-name", "task-1"])
        assert result.exit_code == 0, result.output
        assert "task-1" in result.output
        assert "task-0" not in result.output
        assert "task-2" not in result.output

    def test_ls_tasks_empty(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(app, ["task", "ls"])
        assert result.exit_code == 0, result.output
        assert "No tasks found" in result.output  # Adjust based on your output message


class TestDelete:
    def test_delete_task(self, db_fixture, cli_create_queue_from_config):
        # Create a task first
        task_id = db_fixture.create_task(
            task_name="task-to-delete",
            args={"key": "value"},
            metadata={"tag": "test"},
            cmd="echo hello",
        )
        result = runner.invoke(app, ["task", "delete", task_id, "--yes"])
        assert result.exit_code == 0, result.output

        # Verify the task is deleted
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task is None

    def test_delete_non_existent_task(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(app, ["task", "delete", "non_existent_task_id", "--yes"])
        assert result.exit_code != 0, result.output
        assert "Task not found" in result.output
