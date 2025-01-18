import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial

executor = ThreadPoolExecutor()


async def run_in_threadpool(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    wrapped_func = partial(func, *args, **kwargs)
    return await loop.run_in_executor(executor, wrapped_func)  # type: ignore
