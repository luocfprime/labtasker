import os
import subprocess

import pytest

from labtasker.server.config import ServerConfig

from .fixtures.fixture_database import (
    db_fixture,
    mock_db,
    mock_session,
    queue_args,
    real_db,
    task_args,
)


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


# @pytest.fixture
# def test_server_config(monkeypatch):
#     """Set test environment variables."""
#     monkeypatch.setenv("DB_NAME", "test_db")
#     monkeypatch.setenv("DB_HOST", "localhost")
#     monkeypatch.setenv("DB_PORT", "27017")
#     monkeypatch.setenv("ADMIN_USERNAME", "test_admin")
#     monkeypatch.setenv("ADMIN_PASSWORD", "test_password")
#     return ServerConfig()


@pytest.fixture(scope="session", autouse=True)
def reset_singletons():
    """Reset all singletons before each test."""
    # Reset singleton instances directly for testing
    ServerConfig._instance = None  # Direct reset
    yield  # Allow test to run


@pytest.fixture(scope="session", autouse=True)
def cleanup_docker(request):
    """Clean up Docker containers and networks after tests."""
    yield

    if "integration" in request.node.keywords:
        try:
            subprocess.run(
                ["docker-compose", "-f", "tests/docker-compose.yml", "down", "-v"],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"Failed to clean up Docker resources: {e}")
