import re
from ast import literal_eval

import pytest
from typer.testing import CliRunner

from labtasker.client.cli import app
from tests.test_client.test_cli.test_queue import cli_create_queue_from_config

runner = CliRunner()

# Mark the entire file as e2e, integration and unit tests
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.integration,
    pytest.mark.unit,
    pytest.mark.dependency(  # depends on creating valid queue via cli
        depends=[
            "tests/test_client/test_cli/test_queue.py::TestCreate::test_create_no_metadata"
        ],
        scope="session",
    ),
]


class TestCreate:
    def test_create_worker_by_default(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "worker",
                "create",
            ],
        )
        assert result.exit_code == 0, result.output

    def test_create_worker(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "worker",
                "create",
                "--worker-name",
                "new-test-worker",
                "--max-retries",
                "3",
                "--metadata",
                '{"tag": "test"}',
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify worker is created
        worker = db_fixture._workers.find_one({"worker_name": "new-test-worker"})
        assert worker is not None
        assert worker["max_retries"] == 3
        assert worker["metadata"] == literal_eval('{"tag": "test"}')

    def test_create_worker_no_metadata(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "worker",
                "create",
                "--worker-name",
                "new-test-worker-no-metadata",
                "--max-retries",
                "3",
            ],
        )
        assert result.exit_code == 0, result.output

        worker = db_fixture._workers.find_one(
            {"worker_name": "new-test-worker-no-metadata"}
        )
        assert worker is not None
        assert worker["max_retries"] == 3
        assert worker["metadata"] == {}


@pytest.fixture
def cli_create_worker_by_default() -> str:
    """
    Create a default worker.
    Returns: worker id

    """
    result = runner.invoke(
        app,
        [
            "worker",
            "create",
        ],
    )
    assert result.exit_code == 0, result.output
    # uuid4 pattern
    worker_id = re.search(
        r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}",
        result.output,
    ).group(0)
    return worker_id


class TestDelete:
    def test_delete_worker(
        self, db_fixture, cli_create_queue_from_config, cli_create_worker_by_default
    ):
        worker_id = cli_create_worker_by_default
        result = runner.invoke(
            app,
            [
                "worker",
                "delete",
                worker_id,
                "--yes",
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify the worker is deleted
        worker = db_fixture._workers.find_one({"_id": worker_id})
        assert worker is None

    def test_delete_non_existent_worker(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "worker",
                "delete",
                "non_existent_worker_id",
                "--yes",
            ],
        )
        assert result.exit_code != 0, result.output
        # Should trigger 404 not found -> typer.BadParameter
        assert "Worker not found" in result.output


class TestLs:
    @pytest.fixture
    def setup_workers(self, db_fixture, cli_create_queue_from_config):
        queue_id = db_fixture._queues.find_one(
            {"queue_name": cli_create_queue_from_config.queue.queue_name}
        )["_id"]
        # Create multiple workers for testing
        for i in range(5):
            db_fixture.create_worker(
                queue_id=queue_id,
                worker_name=f"worker-{i}",
                metadata={"tag": f"test-{i}"},
                max_retries=3,
            )

    def test_ls_workers(self, db_fixture, setup_workers):
        result = runner.invoke(app, ["worker", "ls"])
        assert result.exit_code == 0, result.output

        # Check that the output contains the created workers
        for i in range(5):
            assert f"worker-{i}" in result.output

    def test_ls_workers_with_filter(self, db_fixture, setup_workers):
        result = runner.invoke(app, ["worker", "ls", "--worker-name", "worker-1"])
        assert result.exit_code == 0, result.output
        assert "worker-1" in result.output
        assert "worker-0" not in result.output
        assert "worker-2" not in result.output

    def test_ls_workers_empty(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(app, ["worker", "ls"])
        assert result.exit_code == 0, result.output

    def test_ls_workers_pager(self, db_fixture, setup_workers):
        result = runner.invoke(app, ["worker", "ls", "--pager"])
        assert result.exit_code == 0, result.output

        # Check that the output contains the created workers
        for i in range(5):
            assert f"worker-{i}" in result.output
