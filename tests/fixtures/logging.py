import logging.config

import pytest
from loguru import logger

from labtasker.client.core.logging import reset_logger
from labtasker.server.logging import log_config


@pytest.fixture
def silence_logger():
    logger.remove()
    yield
    reset_logger()  # restore logger


@pytest.fixture
def server_logger_level_to_error():
    log_config_error = log_config.copy()
    log_config_error["loggers"]["app"]["level"] = "ERROR"
    logging.config.dictConfig(log_config_error)
    yield
    logging.config.dictConfig(log_config)
