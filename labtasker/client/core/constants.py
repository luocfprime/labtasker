import os
from pathlib import Path

_LABTASKER_ROOT = Path(os.environ.get("LABTASKER_ROOT", ".labtasker"))


def get_labtasker_root():
    return _LABTASKER_ROOT


def get_labtasker_client_config_path():
    return _LABTASKER_ROOT / "client.env"


def get_labtasker_log_root():
    return _LABTASKER_ROOT / "logs"
