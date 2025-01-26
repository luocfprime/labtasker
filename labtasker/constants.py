import os
from enum import Enum
from pathlib import Path


class Priority(int, Enum):
    LOW = 0
    MEDIUM = 10  # default
    HIGH = 20


LABTASKER_ROOT = Path(os.environ.get("LABTASKER_ROOT", ".labtasker"))
LABTASKER_CLIENT_CONFIG_PATH = LABTASKER_ROOT / "client.env"
LABTASKER_LOG_ROOT = LABTASKER_ROOT / "logs"
