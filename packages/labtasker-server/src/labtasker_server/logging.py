from __future__ import annotations

import logging
import time
from collections.abc import Callable
from time import struct_time


class UTCFormatter(logging.Formatter):
    converter: Callable[[float | None], struct_time] = time.gmtime


def uvicorn_log_config() -> dict[str, object]:
    formatter = {
        "()": UTCFormatter,
        "format": ("%(asctime)s.%(msecs)03dZ %(levelname)s [labtasker-server] %(message)s"),
        "datefmt": "%Y-%m-%dT%H:%M:%S",
    }
    handler = {
        "class": "logging.StreamHandler",
        "formatter": "labtasker-server",
        "stream": "ext://sys.stderr",
    }
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"labtasker-server": formatter},
        "handlers": {"labtasker-server": handler},
        "loggers": {
            "labtasker_server": {
                "handlers": ["labtasker-server"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn": {
                "handlers": ["labtasker-server"],
                "level": "INFO",
                "propagate": False,
            },
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {
                "handlers": ["labtasker-server"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }
