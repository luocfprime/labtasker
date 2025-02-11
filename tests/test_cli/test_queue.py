from ast import literal_eval

import pytest
from typer.testing import CliRunner

from labtasker.client.cli import app
from labtasker.security import verify_password

runner = CliRunner()


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.unit
@pytest.mark.dependency(name="TestCreate")
class TestCreate:
    @pytest.mark.parametrize(
        "metadata",
        [
            "{'tag': 'test'}",
            "{'tag': 'test', 'tag2': 'test2'}",
            "{'foo': {'bar': [0, 1, 2]}}",
        ],
    )
    def test_create(self, db_fixture, metadata):
        result = runner.invoke(
            app,
            [
                "queue",
                "create",
                "--queue-name",
                "new-test-queue",
                "--password",
                "new-test-password",
                "--metadata",
                metadata,
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify queue is created
        queue = db_fixture._queues.find_one({"queue_name": "new-test-queue"})
        assert queue is not None
        assert verify_password("new-test-password", queue["password"])
        assert queue["metadata"] == literal_eval(metadata)

    def test_create_no_metadata(self, db_fixture):
        result = runner.invoke(
            app,
            [
                "queue",
                "create",
                "--queue-name",
                "new-test-queue",
                "--password",
                "new-test-password",
            ],
        )
        assert result.exit_code == 0, result.output
        queue = db_fixture._queues.find_one({"queue_name": "new-test-queue"})
        assert queue is not None


@pytest.fixture
def cli_create_queue_from_config(client_config):
    """
    Create a queue using client config and cli.
    This is for queue testing that requires creating a queue in advance.
    """
    result = runner.invoke(
        app,
        [
            "queue",
            "create",
            "--queue-name",
            client_config.queue_name,
            "--password",
            client_config.password.get_secret_value(),
        ],
    )
    assert result.exit_code == 0, result.output
    return client_config


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.unit
@pytest.mark.dependency(depends=["TestCreate"])
class TestGet:
    def test_get(self, db_fixture, cli_create_queue_from_config):
        # get queue
        result = runner.invoke(app, ["queue", "get"])
        assert result.exit_code == 0, result.output
        assert cli_create_queue_from_config.queue_name in result.output, result.output


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.unit
@pytest.mark.dependency(depends=["TestCreate"])
class TestDelete:
    def test_delete(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "queue",
                "delete",
                "-y",
            ],
        )
        assert result.exit_code == 0, result.output
