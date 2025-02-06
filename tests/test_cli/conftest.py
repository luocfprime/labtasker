import pytest

from tests.fixtures.server.sync_app import test_app


@pytest.fixture(autouse=True, scope="session")
def patch_httpx_client(monkeypatch, test_type, test_app):
    """Patch the httpx client"""

    monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app)
