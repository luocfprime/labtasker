import os
from pathlib import Path
from shutil import rmtree

import pytest

from labtasker.client.core.config import (
    ClientConfig,
    get_client_config,
    init_labtasker_root,
    load_client_config,
)
from labtasker.client.core.heartbeat import end_heartbeat
from labtasker.security import get_auth_headers
from tests.fixtures.server.sync_app import test_app


@pytest.fixture(autouse=True)
def patch_httpx_client(monkeypatch, test_type, test_app, client_config):
    """Patch the httpx client"""
    if test_type in ["unit", "integration"]:
        auth_headers = get_auth_headers(
            client_config.queue.queue_name, client_config.queue.password
        )
        test_app.headers.update(
            {**auth_headers, "Content-Type": "application/json"},
        )
        monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app)

    # For e2e test, we serve the API service via docker and test with actual httpx client.


@pytest.fixture(autouse=True)
def labtasker_test_root(proj_root, monkeypatch):
    """Setup labtasker test root dir and default client config"""
    labtasker_test_root = Path(os.path.join(proj_root, "tmp", ".labtasker"))
    init_labtasker_root(labtasker_root=labtasker_test_root, exist_ok=True)

    os.environ["LABTASKER_ROOT"] = str(labtasker_test_root)

    # Patch the constants
    monkeypatch.setattr(
        "labtasker.client.core.paths._LABTASKER_ROOT", labtasker_test_root
    )

    yield labtasker_test_root

    # Tear Down
    rmtree(labtasker_test_root)


@pytest.fixture(autouse=True)
def client_config(labtasker_test_root) -> ClientConfig:
    load_client_config(skip_if_loaded=False, disable_warning=True)  # reload client env
    return get_client_config()


@pytest.fixture(autouse=True)
def reset_heartbeat():
    """Reset heartbeat manager after each testcase. So that some crashed test does not affect others."""
    yield
    end_heartbeat(raise_error=False)
