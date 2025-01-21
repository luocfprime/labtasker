import pytest
from starlette.testclient import TestClient

from labtasker.server.endpoints import app


@pytest.fixture
def test_app(db_fixture):
    """Create test app with mock database."""
    # Depends on db_fixture to ensure db is patched
    # To trigger lifespan function, see https://www.starlette.io/lifespan/#running-lifespan-in-tests
    # which is not intended for sync tests
    yield TestClient(app)
