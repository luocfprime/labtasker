import pytest
import tomlkit
from typer.testing import CliRunner

from labtasker.client.cli import app
from labtasker.client.core.config import ClientConfig
from labtasker.client.core.paths import get_labtasker_client_config_path
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


def test_config_edit_single_replace(setup_editor, setup_confirm, client_config):
    """Test single replacement edit operation"""
    setup_confirm.configure([True])

    # Configure edit operation: replace queue name and password
    setup_editor.configure(
        [
            # replace test-queue with new-test-queue
            (r'queue_name\s*=\s*["\']test-queue["\']', 'queue_name = "new-test-queue"'),
            # replace test-password with new-test-password
            (
                r'password\s*=\s*["\']test-password["\']',
                'password = "new-test-password"',
            ),
        ]
    )

    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert setup_editor.call_count == 1
    assert "Configuration updated successfully" in result.stdout

    # Try to load config
    config_file = get_labtasker_client_config_path()
    with open(config_file, "rb") as f:
        new_config = ClientConfig.model_validate(tomlkit.load(f))

    old_config = client_config

    assert (
        old_config.queue.queue_name != new_config.queue.queue_name
    ), new_config.queue.queue_name
    assert (
        old_config.queue.password != new_config.queue.queue_name
    ), new_config.queue.password

    assert new_config.queue.queue_name == "new-test-queue", new_config.queue.queue_name
