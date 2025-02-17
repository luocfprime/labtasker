import pytest
from loguru import logger

from labtasker.client.core.logging import reset_logger


@pytest.fixture
def silence_logger():
    logger.remove()
    yield
    reset_logger()  # restore logger
