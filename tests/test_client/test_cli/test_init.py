import os
from pathlib import Path
from shutil import rmtree

import httpx
import pytest
from noneprompt import Choice, ConfirmPrompt, InputPrompt, ListPrompt
from starlette.status import HTTP_403_FORBIDDEN
from typer.testing import CliRunner

from labtasker.api_models import QueueCreateResponse
from labtasker.client.cli.init import (
    app,
    confirm_set_traceback_filter,
    setup_endpoint_url,
    setup_password,
    setup_queue,
    setup_queue_name,
)
from labtasker.client.core.exceptions import (
    LabtaskerConnectError,
    LabtaskerHTTPStatusError,
)

runner = CliRunner()


def mock_prompts(monkeypatch, inputs):
    """Generic mock for noneprompt input functions"""

    def mock_prompt(self):
        if not inputs:
            raise IndexError("No more mock inputs")
        value = inputs.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(InputPrompt, "prompt", mock_prompt)
    monkeypatch.setattr(ListPrompt, "prompt", mock_prompt)
    monkeypatch.setattr(ConfirmPrompt, "prompt", mock_prompt)


@pytest.mark.unit
def test_setup_endpoint_url_valid(monkeypatch):
    mock_prompts(monkeypatch, ["https://valid.url"])
    monkeypatch.setattr(
        "labtasker.client.cli.init.health_check",
        lambda **kwargs: type("Resp", (), {"status": "healthy"}),
    )

    url, verified = setup_endpoint_url()
    assert url == "https://valid.url/"
    assert verified is True


@pytest.mark.unit
def test_setup_endpoint_url_retry_flow(monkeypatch):
    mock_prompts(
        monkeypatch,
        [
            "https://retry.url",  # First invalid input
            Choice("Proceed with next step", data="next"),  # Proceed despite unhealthy
        ],
    )
    # Fixed mock to properly raise exception using lambda
    monkeypatch.setattr(
        "labtasker.client.cli.init.health_check",
        lambda **kwargs: (_ for _ in ()).throw(  # Generator that throws error
            LabtaskerConnectError(
                message="Connection refused",
                request=httpx.Request("GET", "https://invalid_url"),
            )
        ),
    )

    url, verified = setup_endpoint_url()
    assert url == "https://retry.url/"
    assert verified is False


@pytest.mark.unit
def test_setup_queue_name_valid(monkeypatch):
    mock_prompts(monkeypatch, ["valid-queue-123"])
    name = setup_queue_name()
    assert name == "valid-queue-123"


@pytest.mark.unit
def test_setup_password_matching(monkeypatch):
    mock_prompts(monkeypatch, ["password123", "password123"])
    result = setup_password()
    assert result == "password123"


@pytest.mark.unit
def test_setup_password_mismatch(monkeypatch):
    mock_prompts(
        monkeypatch,
        [
            "password123",
            "wrongpass",
            "matching",  # Retry
            "matching",
        ],
    )
    result = setup_password()
    assert result == "matching"


@pytest.mark.unit
def test_setup_queue_creation(monkeypatch):
    mock_prompts(
        monkeypatch, ["test-queue", "password", "password", True]  # Confirm creation
    )
    monkeypatch.setattr(
        "labtasker.client.cli.init.create_queue",
        lambda *args, **kwargs: QueueCreateResponse(queue_id="test-queue-id"),
    )
    monkeypatch.setattr(
        "labtasker.client.cli.init.get_queue",
        lambda **kwargs: (_ for _ in ()).throw(  # Generator that throws error
            LabtaskerHTTPStatusError(  # if queue not exist, get_queue would throw an error, which is expected
                message="403 forbidden",
                request=httpx.Request("GET", "https://invalid_url"),
                response=httpx.Response(
                    status_code=HTTP_403_FORBIDDEN,
                    request=httpx.Request("GET", "https://invalid_url"),
                ),
            )
        ),
    )

    name, pwd = setup_queue("http://valid.url", True)
    assert name == "test-queue"
    assert pwd == "password"


@pytest.mark.unit
def test_confirm_traceback_filter_yes(monkeypatch):
    mock_prompts(monkeypatch, [Choice(name="yes", data=True)])
    result = confirm_set_traceback_filter()
    assert result is True


@pytest.mark.unit
def test_confirm_traceback_filter_no(monkeypatch):
    mock_prompts(monkeypatch, [Choice(name="no", data=False)])
    result = confirm_set_traceback_filter()
    assert result is False


@pytest.mark.e2e
class TestInit:
    @pytest.fixture(autouse=True)
    def setup_erase_db(self, db_fixture):
        pass  # use db_fixture to ensure db is erased after each test

    @pytest.fixture
    def client_config(self):
        pass  # prevent auto-used fixture in conftest loading non-existent client config

    @pytest.fixture
    def patch_httpx_client(self, test_app):
        pass  # prevent auto-used fixture in conftest loading non-existent client config

    @pytest.fixture(autouse=True)
    def labtasker_test_root(self, proj_root, monkeypatch):
        """Override the original labtasker_test_root from conftest to only patch path, not create template"""
        labtasker_test_root = Path(os.path.join(proj_root, "tmp", ".labtasker"))
        if labtasker_test_root.exists():
            rmtree(labtasker_test_root)

        os.environ["LABTASKER_ROOT"] = str(labtasker_test_root)

        # Patch the constants
        monkeypatch.setattr(
            "labtasker.client.core.paths._LABTASKER_ROOT", labtasker_test_root
        )

        yield labtasker_test_root

        # Tear Down
        if labtasker_test_root.exists():
            rmtree(labtasker_test_root)

    @pytest.fixture
    def endpoint_url(self, test_type):
        assert test_type == "e2e"
        return "http://localhost:9321"  # TODO: hard coded

    def test_normal_flow(self, monkeypatch, labtasker_test_root, endpoint_url):
        mock_prompts(
            monkeypatch,
            [
                endpoint_url,
                "test-init-queue",  # queue name
                "my-password",  # pass
                "my-password",  # repeat
                True,  # Confirm creation
                Choice("yes", data=True),  # Confirm traceback filter
            ],
        )

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "QueueCreateResponse" in result.output
        assert "Configuration initialized successfully" in result.output

    def test_skip_queue_creation(self, monkeypatch, labtasker_test_root, endpoint_url):
        mock_prompts(
            monkeypatch,
            [
                endpoint_url,
                "test-init-queue",  # queue name
                "my-password",
                "my-password",
                False,  # Skip queue creation
                Choice("yes", data=True),  # Confirm traceback filter
            ],
        )
        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "QueueCreateResponse" not in result.output
        assert "Configuration initialized successfully" in result.output

    def test_connection_retry_flow(
        self, monkeypatch, labtasker_test_root, endpoint_url
    ):
        mock_prompts(
            monkeypatch,
            [
                "https://bad.url",
                Choice("Edit the URL", data="edit"),
                endpoint_url,
                "test-queue",
                "password",
                "password",
                True,  # Confirm creation
                Choice("yes", data=True),
            ],
        )

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 0
        assert "QueueCreateResponse" in result.output
        assert "Configuration initialized successfully" in result.output
