import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from labtasker.server.endpoints import app

# if you're using pytest, you'll need to to add an async marker like:
# @pytest.mark.anyio  # using https://github.com/agronholm/anyio
# or install and configure pytest-asyncio (https://github.com/pytest-dev/pytest-asyncio)


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def test_app(db_fixture):
    # Depends on db_fixture to ensure db is patched
    # note: you _must_ set `base_url` for relative urls like "/" to work
    async with LifespanManager(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


@pytest.mark.unit
@pytest.mark.anyio
async def test_health(test_app):
    r = await test_app.get("/health")
    assert r.status_code == 200, f"{r.json()}"
