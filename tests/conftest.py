import os

import pytest

from labtasker.server.config import get_server_config, init_server_config
from tests.fixtures.database import *  # noqa: F401, F403


def pytest_addoption(parser):
    """Add custom options to pytest."""

    parser.addoption(
        "--manual-docker",
        action="store_true",
        default=False,
        help="Manually control the instantiation of docker compose service",
    )


@pytest.fixture(scope="session")
def proj_root(pytestconfig) -> str:
    return str(pytestconfig.rootdir)  # noqa


@pytest.fixture(scope="session")
def test_type(request):
    """
    Fixture to determine the current test type (e.g., 'unit', 'integration', 'e2e').
    Priority: CLI marker (-m) > Test-specific marker > Environment variable > Default.
    """
    # 1. Check the CLI marker (-m option)
    cli_marker = request.config.option.markexpr
    if cli_marker in ["unit", "integration", "e2e"]:  # Add more types if needed
        return cli_marker

    # 2. Check test-specific markers
    if "unit" in request.node.keywords:
        return "unit"
    elif "integration" in request.node.keywords:
        return "integration"
    elif "e2e" in request.node.keywords:
        return "e2e"

    # 3. Fallback to environment variable
    env_test_type = os.getenv("TEST_TYPE")
    if env_test_type in ["unit", "integration", "e2e"]:  # Add more types if needed
        return env_test_type

    # 4. Default to 'unit' if nothing else is specified
    return "unit"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def db_fixture(test_type, request, monkeypatch):
    """
    Dynamic database fixture that supports both mock and real databases.
    """
    if test_type in ["integration", "e2e"]:
        db = request.getfixturevalue("real_db")
    elif test_type == "unit":
        db = request.getfixturevalue("mock_db")
    else:
        raise ValueError(
            "Database testcases must be tagged with either 'unit' or 'integration'"
        )

    return db


@pytest.fixture(scope="session")
def server_env_file(proj_root):
    return os.path.join(proj_root, "server.example.env")


@pytest.fixture(scope="session")
def manual_docker(request):
    """Check if user asked manually control Docker compose service setup and teardown during the test."""
    return request.config.option.manual_docker


@pytest.fixture(scope="session")
def docker_compose_project_name(manual_docker, docker_compose_project_name) -> str:
    """Generate a project name using the current process PID. Override this
    fixture in your tests if you need a particular project name."""

    if manual_docker:
        return "pytest-labtasker"
    return docker_compose_project_name


@pytest.fixture(scope="session")
def docker_compose_file(proj_root):
    """Get an absolute path to the `docker-compose.yml` file. Override from pytest-docker."""
    return os.path.join(proj_root, "docker-compose.yml")


@pytest.fixture(scope="session")
def docker_setup(manual_docker, server_env_file, test_type):
    """Override the pytest-docker docker_setup to take in env file"""
    if manual_docker:
        return ["version"]  # dummy command
    if test_type == "integration":
        # only start mongodb (after post init) for integration test
        return [f"--env-file {server_env_file} up --build -d mongo-post-init"]
    elif test_type == "e2e":
        return [f"--env-file {server_env_file} up --build -d"]


@pytest.fixture(scope="session")
def docker_cleanup(manual_docker, proj_root, server_env_file):
    """Override the pytest-docker docker_cleanup to take in env file"""
    if manual_docker:
        return ["version"]  # dummy command
    return [f"--env-file {server_env_file} down --remove-orphans --volumes"]


# auto use fixtures ------------------------------------------------


@pytest.fixture(autouse=True)
def setup_teardown_db(db_fixture):
    """Invoke db_fixture to automatically clear database after each test"""
    pass


@pytest.fixture(scope="session", autouse=True)
def allow_unsafe():
    """Enable unsafe operations for testing."""
    os.environ["ALLOW_UNSAFE_BEHAVIOR"] = "true"
    yield
    if "ALLOW_UNSAFE_BEHAVIOR" in os.environ:
        del os.environ["ALLOW_UNSAFE_BEHAVIOR"]


@pytest.fixture(scope="session", autouse=True)
def server_config(test_type, server_env_file):
    # Initialize server config for testing
    if test_type in ["unit", "integration"]:
        # Only in unit test and integration test, we can modify server config
        # through environment variables.
        # In end-to-end testing, server config is loaded from env file via docker compose.
        # Therefore, we cannot modify server config by modifying environment variables here.
        # See https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/.

        # Spin really fast for unit and integration testing,
        os.environ["PERIODIC_TASK_INTERVAL"] = "0.01"

    init_server_config(server_env_file)

    yield get_server_config()


@pytest.fixture(autouse=True)
def setup_docker_service(test_type, request):
    """Setup docker if test_type is integration or e2e test"""
    if test_type in ["integration", "e2e"]:
        # launch docker compose via triggering fixture
        request.getfixturevalue("docker_services")


@pytest.fixture(autouse=True)
def patch_db(monkeypatch, test_type, db_fixture):
    if test_type in ["unit", "integration"]:
        # patch the global _db_service as db_fixture so that get_db() has testing behavior
        monkeypatch.setattr("labtasker.server.database._db_service", db_fixture)
