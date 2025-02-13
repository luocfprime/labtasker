import contextvars
import os
from pathlib import Path

from labtasker.utils import get_current_time

_LABTASKER_ROOT = Path(os.environ.get("LABTASKER_ROOT", ".labtasker"))

_labtasker_log_dir = contextvars.ContextVar("labtasker_log_dir")
_labtasker_log_dir.set(os.environ.get("LABTASKER_LOG_DIR", None))


def get_labtasker_root():
    return _LABTASKER_ROOT


def get_labtasker_client_config_path():
    return _LABTASKER_ROOT / "client.env"


def get_labtasker_log_root():
    return _LABTASKER_ROOT / "logs"


def set_labtasker_log_dir(task_id: str, set_env: bool = False, overwrite: bool = False):
    """
    Set the log dir for labtasker.
    Args:
        task_id: current task that is being executed.
        set_env: whether set LABTASKER_LOG_DIR.
        overwrite: whether overwrite existing setting. Useful for preventing accidentally overwriting log dir.

    Returns:

    """
    if not overwrite and _labtasker_log_dir.get() is not None:
        raise RuntimeError("Labtasker log directory already set.")
    now = get_current_time().strftime("%Y-%m-%d-%H-%M-%S")
    _labtasker_log_dir.set(get_labtasker_log_root() / "run" / f"run-{task_id}_{now}")
    if set_env:
        os.environ["LABTASKER_LOG_DIR"] = str(_labtasker_log_dir.get())


def get_labtasker_log_dir():
    if _labtasker_log_dir.get() is None:
        raise RuntimeError("Labtasker log directory not set.")
    return _labtasker_log_dir.get()
