from ast import literal_eval

import pytest
from typer.testing import CliRunner

from labtasker.client.cli import app
from labtasker.client.core.config import ClientConfig
from labtasker.security import verify_password

runner = CliRunner()

# Mark the entire file as e2e, integration and unit tests
pytestmark = [pytest.mark.e2e, pytest.mark.integration, pytest.mark.unit]


class TestCreate:
    @pytest.mark.dependency()
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


@pytest.fixture
def cli_create_queue_from_config(client_config) -> ClientConfig:
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
            client_config.queue.queue_name,
            "--password",
            client_config.queue.password.get_secret_value(),
            "--metadata",
            '{"tag": "test"}',  # TODO: hard-coded
        ],
    )
    assert result.exit_code == 0, result.output
    return client_config


@pytest.mark.dependency(depends=["TestCreate::test_create_no_metadata"])
class TestGet:
    def test_get(self, db_fixture, cli_create_queue_from_config):
        # get queue
        result = runner.invoke(app, ["queue", "get"])
        assert result.exit_code == 0, result.output
        assert (
            cli_create_queue_from_config.queue.queue_name in result.output
        ), result.output


@pytest.mark.dependency(depends=["TestCreate::test_create_no_metadata"])
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


@pytest.mark.dependency(depends=["TestCreate::test_create_no_metadata"])
class TestUpdate:
    def test_update_queue_name(self, db_fixture, cli_create_queue_from_config):
        new_name = "updated-queue-name"
        result = runner.invoke(
            app,
            [
                "queue",
                "update",
                "--new-queue-name",
                new_name,
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify the queue name is updated
        queue = db_fixture._queues.find_one({"queue_name": new_name})
        assert queue is not None

    def test_update_queue_password(self, db_fixture, cli_create_queue_from_config):
        new_password = "updated-password"
        result = runner.invoke(
            app,
            [
                "queue",
                "update",
                "--new-password",
                new_password,
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify the password is updated
        queue = db_fixture._queues.find_one(
            {"queue_name": cli_create_queue_from_config.queue.queue_name}
        )
        assert queue is not None
        assert verify_password(new_password, queue["password"])

    def test_update_queue_metadata(self, db_fixture, cli_create_queue_from_config):
        new_metadata = '{"new_key": "new_value"}'
        result = runner.invoke(
            app,
            [
                "queue",
                "update",
                "--metadata",
                new_metadata,
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify the metadata is updated
        queue = db_fixture._queues.find_one(
            {"queue_name": cli_create_queue_from_config.queue.queue_name}
        )
        assert queue is not None
        for key, value in literal_eval(new_metadata).items():
            assert queue["metadata"][key] == value

    def test_update_no_changes(self, db_fixture, cli_create_queue_from_config):
        result = runner.invoke(
            app,
            [
                "queue",
                "update",
            ],
        )
        assert result.exit_code == 0, result.output

        # Verify no changes were made
        queue = db_fixture._queues.find_one(
            {"queue_name": cli_create_queue_from_config.queue.queue_name}
        )
        assert queue is not None
        assert queue["queue_name"] == cli_create_queue_from_config.queue.queue_name
        assert verify_password(
            cli_create_queue_from_config.queue.password.get_secret_value(),
            queue["password"],
        )
        assert queue["metadata"] == literal_eval('{"tag": "test"}')  # TODO: hard-coded
