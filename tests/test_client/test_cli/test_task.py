import io
import re
from ast import literal_eval

import pytest
from typer.testing import CliRunner

from labtasker.client.cli import app
from labtasker.client.cli.task import (
    add_eol_comment,
    commented_seq_from_dict_list,
    dump_commented_seq,
)
from tests.test_client.test_cli.test_queue import cli_create_queue_from_config

runner = CliRunner(
    mix_stderr=False
)  # mix_stderr must be set to False to access result.stderr

# Mark the entire file as e2e, integration and unit tests
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.integration,
    pytest.mark.unit,
    pytest.mark.dependency(
        depends=[
            "tests/test_client/test_cli/test_queue.py::TestCreate::test_create_no_metadata"
        ],
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

    def test_submit_task_positional_args(
        self, db_fixture, cli_create_queue_from_config
    ):
        result = runner.invoke(
            app,
            [
                "task",
                "submit",
                # options
                "--task-name",
                "new-test-task",
                "--metadata",
                '{"tag": "test"}',
                "--",  # delimiter
                # positional args after "--"
                "--foo.bar",
                "hello",
                "--foo.foo",
                "hi",
            ],
        )
        assert result.exit_code == 0, result.output + result.stderr

        # Verify task is created
        task = db_fixture._tasks.find_one({"task_name": "new-test-task"})
        assert task is not None
        assert task["args"] == {"foo": {"bar": "hello", "foo": "hi"}}
        assert task["metadata"] == literal_eval('{"tag": "test"}')


@pytest.fixture
def setup_pending_task(db_fixture, cli_create_queue_from_config):
    """Set up a task in PENDING state in current queue."""
    queue_id = db_fixture._queues.find_one(
        {"queue_name": cli_create_queue_from_config.queue.queue_name}
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
    """Set up a task in RUNNING state in current queue."""
    queue_id = db_fixture._queues.find_one(
        {"queue_name": cli_create_queue_from_config.queue.queue_name}
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
            {"queue_name": cli_create_queue_from_config.queue.queue_name}
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

    @pytest.mark.parametrize("fmt", ["jsonl", "yaml"])
    def test_ls_tasks(self, db_fixture, setup_tasks, fmt):
        result = runner.invoke(app, ["task", "ls", "--fmt", fmt])
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

        result = runner.invoke(
            app, ["task", "ls", "--extra-filter", '{"metadata.tag": "test-1"}']
        )
        assert result.exit_code == 0, result.output
        assert "task-1" in result.output
        assert "task-0" not in result.output
        assert "task-2" not in result.output

    def test_ls_tasks_empty(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(app, ["task", "ls"])
        assert result.exit_code == 0, result.output


class TestDelete:
    def test_delete_task(self, db_fixture, setup_pending_task):
        task_id = setup_pending_task
        result = runner.invoke(app, ["task", "delete", task_id, "--yes"])
        assert result.exit_code == 0, result.output

        # Verify the task is deleted
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task is None

    def test_delete_non_existent_task(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(app, ["task", "delete", "non_existent_task_id", "--yes"])
        assert result.exit_code != 0, result.output
        assert "Task not found" in result.stderr


class TestUpdate:
    @pytest.fixture(autouse=True)
    def auto_confirm_once(self, setup_confirm):
        # confirm to see the final result output (pager -> stdout)
        setup_confirm.configure([True])

    @pytest.mark.parametrize(
        "query_mode",
        ["task-id", "task-name", "extra-filter"],
    )
    def test_update_task_no_interactive(
        self, db_fixture, setup_pending_task, query_mode
    ):
        task_id = setup_pending_task
        updates = ["task_name=updated-test-task", "cmd='echo hi'"]

        if query_mode == "task-id":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--task-id",
                    task_id,
                    "-u",
                    updates[0],
                    "-u",
                    updates[1],
                ],
            )
        elif query_mode == "task-name":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--task-name",
                    "test-task",
                    "-u",
                    updates[0],
                    "-u",
                    updates[1],
                ],
            )
        elif query_mode == "extra-filter":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--extra-filter",
                    f'{{"_id": "{task_id}" }}',
                    "-u",
                    updates[0],
                    "-u",
                    updates[1],
                ],
            )
        else:
            assert False

        assert result.exit_code == 0, result.output

        # check output
        # should be something like:

        # - task_id: b77bd500-e9dd-473c-9524-520743763b29
        #   queue_id: d205ceed-3836-4940-84eb-caf1940d95f5
        #   status: pending
        #   task_name: updated-test-task                    # Modified
        #   created_at: 2025-02-23 11:41:41.908000
        #   start_time:
        #   last_heartbeat:
        #   last_modified: 2025-02-23 11:41:41.933000
        #   heartbeat_timeout: 60.0
        #   task_timeout: 300
        #   max_retries: 3
        #   retries: 0
        #   priority: 10
        #   metadata:
        #     tag: test
        #   args:
        #     key: value
        #   cmd: echo hi                    # Modified
        #   summary: {}
        #   worker_id:

        # search for modified line
        assert re.search(
            r"task_name:\s+updated-test-task\s+#\s+Modified", result.output
        ), result.output
        assert re.search(r"cmd:\s+echo hi\s+#\s+Modified", result.output), result.output

        # Verify the task is updated
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task is not None
        assert task["task_name"] == "updated-test-task"

    @pytest.mark.parametrize(
        "query_mode",
        ["task-id", "task-name", "extra-filter"],
    )
    def test_update_task_no_interactive_positional_args(
        self, db_fixture, setup_pending_task, query_mode
    ):
        task_id = setup_pending_task

        update_positional_args = ["task-name=updated-test-task", "cmd=echo hi"]

        if query_mode == "task-id":
            result = runner.invoke(
                app,
                ["task", "update", "--task-id", task_id, "--", *update_positional_args],
            )
        elif query_mode == "task-name":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--task-name",
                    "test-task",
                    "--",
                    *update_positional_args,
                ],
            )
        elif query_mode == "extra-filter":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--extra-filter",
                    f'{{"_id": "{task_id}" }}',
                    "--",
                    *update_positional_args,
                ],
            )
        else:
            assert False

        assert result.exit_code == 0, result.output

        # check output
        # should be something like:

        # - task_id: b77bd500-e9dd-473c-9524-520743763b29
        #   queue_id: d205ceed-3836-4940-84eb-caf1940d95f5
        #   status: pending
        #   task_name: updated-test-task                    # Modified
        #   created_at: 2025-02-23 11:41:41.908000
        #   start_time:
        #   last_heartbeat:
        #   last_modified: 2025-02-23 11:41:41.933000
        #   heartbeat_timeout: 60.0
        #   task_timeout: 300
        #   max_retries: 3
        #   retries: 0
        #   priority: 10
        #   metadata:
        #     tag: test
        #   args:
        #     key: value
        #   cmd: echo hello
        #   summary: {}
        #   worker_id:

        # search for modified line
        assert re.search(
            r"task_name:\s+updated-test-task\s+#\s+Modified", result.output
        ), result.output

        # Verify the task is updated
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task is not None
        assert task["task_name"] == "updated-test-task"

    @pytest.mark.parametrize(
        "query_mode",
        ["task-id", "task-name", "extra-filter"],
    )
    def test_update_task_interactive(
        self, db_fixture, setup_pending_task, query_mode, setup_editor
    ):
        # mock editor
        setup_editor.configure(
            (r"task_name:\s*test-task", r"task_name: updated-test-task")
        )

        task_id = setup_pending_task

        if query_mode == "task-id":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--task-id",
                    task_id,
                ],
            )
        elif query_mode == "task-name":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--task-name",
                    "test-task",
                ],
            )
        elif query_mode == "extra-filter":
            result = runner.invoke(
                app,
                [
                    "task",
                    "update",
                    "--extra-filter",
                    f'{{"_id": "{task_id}" }}',
                ],
            )
        else:
            assert False

        assert result.exit_code == 0, result.output + result.stderr

        assert re.search(
            r"task_name:\s+updated-test-task\s+#\s+Modified", result.output
        ), result.output

        # Verify the task is updated
        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task is not None
        assert task["task_name"] == "updated-test-task"

    def test_update_task_readonly_field(self, db_fixture, setup_pending_task):
        task_id = setup_pending_task
        update = "task_name=updated-test-task"

        # when --reset-pending is set,
        # "status" becomes readonly field since it will be handled internally
        result = runner.invoke(
            app,
            [
                "task",
                "update",
                "--extra-filter",
                f'{{"_id": "{task_id}", "status": "finished"}}',
                "-u",
                update,
                "--reset-pending",
            ],
        )

        # the update would still be successful, only with the "status" field being ignored
        assert result.exit_code == 0, result.output + result.stderr

        # check if the warning showed up
        assert result.stderr.find(
            "You are not supposed to modify it. Your modification to this field will be ignored."
        ), result.stderr

        task = db_fixture._tasks.find_one({"_id": task_id})
        assert task is not None
        assert task["status"] == "pending"


class TestUtilities:
    def test_commented_seq_from_dict_list(self):
        entries = [{"key1": "value1"}, {"key2": "value2"}]
        result = commented_seq_from_dict_list(entries)
        assert len(result) == 2
        assert result[0]["key1"] == "value1"
        assert result[1]["key2"] == "value2"

    def test_dump_commented_yaml(self):
        commented_seq = commented_seq_from_dict_list([{"key": "value"}])
        s = io.StringIO()
        for d in commented_seq:
            add_eol_comment(d, fields=["key"], comment="This is a comment")
        dump_commented_seq(commented_seq, s)
        assert re.search(
            r"- key: value\s+# This is a comment", s.getvalue()
        ), s.getvalue()
