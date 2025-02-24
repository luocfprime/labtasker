import pytest
from typer.testing import CliRunner

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


# def test_config():
#     result = runner.invoke(
#         app,
#         [
#             "config",
#             "--api-base-url",
#             "http://localhost:9090",
#             "--queue-name",
#             "new-test-queue",
#             "--password",
#             "new-test-password",
#             "--heartbeat-interval",
#             "100",
#         ],
#         input="y\n",  #  prompt: Configuration at .labtasker/client.env already exists, overwrite? [y/N]: y
#     )
#     assert result.exit_code == 0
#
#     # load the modified config and check if results match
#     with open(get_labtasker_client_config_path(), "rb") as f:
#         config_dict = tomli.load(f)
#     config = ClientConfig.model_validate(config_dict)
#     assert config.api_base_url == HttpUrl("http://localhost:9090")
#     assert config.queue_name == "new-test-queue"
#     assert config.password == SecretStr("new-test-password")
#     assert config.heartbeat_interval == 100
