import contextvars
import os
from pathlib import Path

from labtasker.client.core.exceptions import LabtaskerRuntimeError
from labtasker.utils import get_current_time

_LABTASKER_ROOT = Path(os.environ.get("LABTASKER_ROOT", ".labtasker"))

_labtasker_log_dir = contextvars.ContextVar(
    "labtasker_root",
    default=(
        Path(os.environ["LABTASKER_LOG_DIR"])
        if "LABTASKER_LOG_DIR" in os.environ
        else None
    ),
)


def get_labtasker_root() -> Path:
    return _LABTASKER_ROOT


def get_labtasker_client_config_path() -> Path:
    return _LABTASKER_ROOT / "client.toml"


def get_labtasker_log_root() -> Path:
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
        raise LabtaskerRuntimeError("Labtasker log directory already set.")
    now = get_current_time().strftime("%Y-%m-%d-%H-%M-%S")
    log_dir = get_labtasker_log_root() / "run" / f"run-{task_id}_{now}"
    log_dir.mkdir(parents=True, exist_ok=True)
    _labtasker_log_dir.set(log_dir)
    if set_env:
        os.environ["LABTASKER_LOG_DIR"] = str(_labtasker_log_dir.get())


def get_labtasker_log_dir() -> Path:
    if _labtasker_log_dir.get() is None:
        raise LabtaskerRuntimeError(
            "Labtasker log directory not set. Check if env var `LABTASKER_LOG_DIR` is not overwritten."
        )
    return _labtasker_log_dir.get()


def get_template_dir() -> Path:
    # __file__: labtasker/client/core/paths.py
    # dst:      labtasker/client/templates
    return Path(__file__).parent.parent / "templates"
