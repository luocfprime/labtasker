import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from labtasker.server.endpoints import app


@pytest.fixture
async def async_test_app(db_fixture):
    # Depends on db_fixture to ensure db is patched
    # note: you _must_ set `base_url` for relative urls like "/" to work
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client
