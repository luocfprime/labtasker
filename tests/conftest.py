import os

import pytest

from labtasker.server.config import init_server_config

from .fixtures.database import (  # noqa: F401
    db_fixture,
    get_full_task_args,
    get_task_args,
    mock_db,
    queue_args,
    real_db,
)
from .fixtures.mock_datetime_now import mock_get_current_time  # noqa: F401


@pytest.fixture
def test_type(request):
    """
    Fixture to determine the current test type (e.g., 'unit', 'integration').
    Priority: CLI marker (-m) > Test-specific marker > Environment variable > Default.
    """
    # 1. Check the CLI marker (-m option)
    cli_marker = request.config.option.markexpr
    if cli_marker in ["unit", "integration"]:  # Add more types if needed
        return cli_marker

    # 2. Check test-specific markers
    if "integration" in request.node.keywords:
        return "integration"
    elif "unit" in request.node.keywords:
        return "unit"

    # 3. Fallback to environment variable
    env_test_type = os.getenv("TEST_TYPE")
    if env_test_type in ["unit", "integration"]:  # Add more types if needed
        return env_test_type

    # 4. Default to 'unit' if nothing else is specified
    return "unit"


@pytest.fixture(scope="session")
def docker_compose_command():
    """Docker Compose command for running tests."""
    return "docker-compose"


@pytest.fixture(scope="session", autouse=True)
def allow_unsafe():
    """Enable unsafe operations for testing."""
    os.environ["ALLOW_UNSAFE_BEHAVIOR"] = "true"
    yield
    if "ALLOW_UNSAFE_BEHAVIOR" in os.environ:
        del os.environ["ALLOW_UNSAFE_BEHAVIOR"]


@pytest.fixture(scope="session", autouse=True)
def setup_config(pytestconfig):
    proj_root = pytestconfig.rootdir  # noqa

    # Initialize server config for testing
    os.environ["PERIODIC_TASK_INTERVAL"] = "0.01"  # spin really fast for testing
    env_file_path = os.path.join(proj_root, "server.example.env")

    print(f"Config {env_file_path} exists: {os.path.exists(env_file_path)}")

    init_server_config(env_file_path)


@pytest.fixture
def anyio_backend():
    return "asyncio"
