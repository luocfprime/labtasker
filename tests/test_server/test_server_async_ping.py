import pytest
from starlette.status import HTTP_200_OK

from tests.fixtures.server import async_test_app

# if you're using pytest, you'll need to add an async marker like:
# @pytest.mark.anyio  # using https://github.com/agronholm/anyio
# or install and configure pytest-asyncio (https://github.com/pytest-dev/pytest-asyncio)


@pytest.mark.unit
@pytest.mark.anyio
async def test_health(async_test_app):
    r = await async_test_app.get("/health")
    assert r.status_code == HTTP_200_OK, f"{r.json()}"
