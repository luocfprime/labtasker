import pytest

from labtasker.concurrent import run_in_threadpool

pytestmark = [pytest.mark.unit]


def sample_sync_function(x, y):
    return x + y


@pytest.mark.asyncio
async def test_run_in_threadpool():
    # Call the async function with a synchronous function
    result = await run_in_threadpool(sample_sync_function, 3, 7)

    # Assert the result
    assert result == 10

    # Test with another set of arguments
    result = await run_in_threadpool(sample_sync_function, 10, -5)
    assert result == 5


@pytest.mark.asyncio
async def test_run_in_threadpool_with_kwargs():
    # A sample synchronous function that uses kwargs
    def sample_sync_function_with_kwargs(x, y=0):
        return x * y

    # Call the async function and pass kwargs
    result = await run_in_threadpool(sample_sync_function_with_kwargs, 4, y=5)

    # Assert the result
    assert result == 20

    # Test with default value for y
    result = await run_in_threadpool(sample_sync_function_with_kwargs, 4)
    assert result == 0
