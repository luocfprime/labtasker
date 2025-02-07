import pytest
from pydantic import HttpUrl

from labtasker.client.core.config import init_config_with_default, update_client_config
from tests.fixtures.server.sync_app import test_app


@pytest.fixture(autouse=True)
def patch_httpx_client(monkeypatch, test_type, test_app):
    """Patch the httpx client"""
    if test_type in ["unit", "integration"]:
        try:
            update_client_config(api_base_url=HttpUrl("http://testserver"))
        except RuntimeError:  # ClientConfig not initialized.
            init_config_with_default()  # TODO: client config for testing should be initialized with specified params

        monkeypatch.setattr("labtasker.client.core.api._httpx_client", test_app)

    # For e2e test, we serve the API service via docker and test with actual httpx client.
