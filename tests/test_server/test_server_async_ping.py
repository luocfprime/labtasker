import pytest

from tests.fixtures.server.async_app import test_app

# if you're using pytest, you'll need to add an async marker like:
# @pytest.mark.anyio  # using https://github.com/agronholm/anyio
# or install and configure pytest-asyncio (https://github.com/pytest-dev/pytest-asyncio)


@pytest.mark.unit
@pytest.mark.anyio
async def test_health(test_app):
    r = await test_app.get("/health")
    assert r.status_code == 200, f"{r.json()}"
