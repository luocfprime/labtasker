import os
from pathlib import Path
from shutil import copytree, rmtree

import pytest

from labtasker.client.core.config import get_client_config
from labtasker.security import get_auth_headers
from tests.fixtures.database import mock_db, real_db  # noqa: F401
from tests.fixtures.mock_datetime_now import mock_get_current_time  # noqa: F401
from tests.fixtures.server.sync_app import test_app


@pytest.fixture(autouse=True)
def patch_httpx_client(monkeypatch, test_type, test_app, client_config):
    """Patch the httpx client"""
    if test_type in ["unit", "integration"]:
        auth_headers = get_auth_headers(
            client_config.queue_name, client_config.password
        )
        test_app.headers.update(
            {**auth_headers, "Content-Type": "application/json"},
        )
        monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app)

    # For e2e test, we serve the API service via docker and test with actual httpx client.


@pytest.fixture(autouse=True)
def labtasker_test_root(proj_root, monkeypatch):
    """Setup labtasker test root dir and default client config"""
    labtasker_test_root = Path(os.path.join(proj_root, "tmp"))
    # cp proj_root / .labtasker -> labtasker_test_root
    copytree(
        src=os.path.join(proj_root, ".labtasker"),
        dst=labtasker_test_root,
        dirs_exist_ok=True,
    )
    os.environ["LABTASKER_ROOT"] = str(labtasker_test_root)

    # Patch the constants
    monkeypatch.setattr(
        "labtasker.client.core.constants._LABTASKER_ROOT", labtasker_test_root
    )

    yield labtasker_test_root

    # Tear Down
    rmtree(labtasker_test_root)


@pytest.fixture(autouse=True)
def client_config(labtasker_test_root):
    return get_client_config()
