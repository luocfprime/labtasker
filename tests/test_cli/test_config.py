import pytest
from pydantic import HttpUrl, SecretStr
from typer.testing import CliRunner

from labtasker.client.cli import app
from labtasker.client.core.config import ClientConfig
from labtasker.constants import get_labtasker_client_config_path

runner = CliRunner()


@pytest.mark.unit
def test_config():
    # TODO: old config restore.
    # old_config =
    result = runner.invoke(
        app,
        [
            "config",
            "--api-base-url",
            "http://localhost:8080",
            "--queue-name",
            "test-queue",
            "--password",
            "test-password",
            "--heartbeat-interval",
            "10",
        ],
        input="y\n",  #  prompt: Configuration at .labtasker/client.env already exists, overwrite? [y/N]: y
    )
    assert result.exit_code == 0
    config = ClientConfig(_env_file=get_labtasker_client_config_path())  # noqa
    assert config.api_base_url == HttpUrl("http://localhost:8080")
    assert config.queue_name == "test-queue"
    assert config.password == SecretStr("test-password")
    assert config.heartbeat_interval == 10
