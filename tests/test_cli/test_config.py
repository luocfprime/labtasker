import pytest
from pydantic import HttpUrl, SecretStr
from typer.testing import CliRunner

from labtasker.client.cli import app
from labtasker.client.core.config import ClientConfig
from labtasker.client.core.constants import get_labtasker_client_config_path

runner = CliRunner()


@pytest.mark.e2e
@pytest.mark.integration
@pytest.mark.unit
def test_config():
    result = runner.invoke(
        app,
        [
            "config",
            "--api-base-url",
            "http://localhost:9090",
            "--queue-name",
            "new-test-queue",
            "--password",
            "new-test-password",
            "--heartbeat-interval",
            "100",
        ],
        input="y\n",  #  prompt: Configuration at .labtasker/client.env already exists, overwrite? [y/N]: y
    )
    assert result.exit_code == 0

    # load the modified config and check if results match
    config = ClientConfig(_env_file=get_labtasker_client_config_path())  # noqa
    assert config.api_base_url == HttpUrl("http://localhost:9090")
    assert config.queue_name == "new-test-queue"
    assert config.password == SecretStr("new-test-password")
    assert config.heartbeat_interval == 100
