import os
from pathlib import Path
from shutil import copytree, rmtree

import pytest

from tests.fixtures.database import mock_db, real_db  # noqa: F401
from tests.fixtures.mock_datetime_now import mock_get_current_time  # noqa: F401
from tests.fixtures.server.sync_app import test_app


@pytest.fixture(autouse=True)
def patch_httpx_client(monkeypatch, test_type, test_app):
    """Patch the httpx client"""
    if test_type in ["unit", "integration"]:
        monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app)

    # For e2e test, we serve the API service via docker and test with actual httpx client.


@pytest.fixture(autouse=True)
def labtasker_test_root(proj_root, monkeypatch):
    """Setup labtasker test root dir and default client config"""
    labtasker_test_root = Path(os.path.join(proj_root, "tmp"))
    # cp proj_root / .labtasker -> labtasker_test_root
    copytree(src=os.path.join(proj_root, ".labtasker"), dst=labtasker_test_root)
    os.environ["LABTASKER_ROOT"] = str(labtasker_test_root)

    # Patch the constants
    monkeypatch.setattr("labtasker.constants._LABTASKER_ROOT", labtasker_test_root)

    yield labtasker_test_root

    # Tear Down
    rmtree(labtasker_test_root)
