import json
import subprocess
import threading
from contextvars import ContextVar
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

from packaging import version

from labtasker import __version__
from labtasker.client.core.config import get_client_config
from labtasker.client.core.logging import stderr_console, stdout_console
from labtasker.client.core.paths import (
    get_labtasker_client_config_path,
    get_labtasker_root,
)
from labtasker.utils import get_current_time

# Constants
PACKAGE_NAME = "labtasker"
CHECK_INTERVAL = timedelta(days=1)

# Module state
_process_checked = False
_check_thread: ContextVar[Optional[threading.Thread]] = ContextVar(
    "check_thread", default=None
)


def get_last_version_check_path() -> Path:
    """Return the path to the last version check timestamp"""
    return get_labtasker_root() / ".last-version-check"


@lru_cache(maxsize=1)
def get_configured_should_check() -> bool:
    """Cached access to configuration setting"""
    if get_labtasker_client_config_path().exists():
        return get_client_config().version_check
    # config not initialized
    return True  # default to True


def last_checked() -> datetime:
    """Return the timestamp of the last version check"""
    if not get_last_version_check_path().exists():
        return datetime.min

    try:
        with get_last_version_check_path().open("r") as f:
            return datetime.fromisoformat(f.read().strip())
    except Exception:
        return datetime.min


def update_last_checked() -> None:
    """Update the timestamp of the last version check"""
    parent_dir = get_last_version_check_path().parent
    if not parent_dir.exists():
        return

    with get_last_version_check_path().open("w") as f:
        f.write(get_current_time().isoformat())


def should_check() -> bool:
    """Determine if a version check should be performed"""
    if not get_configured_should_check():
        return False

    if _process_checked:
        return False

    return get_current_time() - last_checked() >= CHECK_INTERVAL


def _check_pip_versions() -> None:
    """Check package versions using pip index versions"""
    current_version_str = __version__
    current_version = version.parse(current_version_str)

    try:
        # Run pip index versions with JSON output
        result = subprocess.run(
            ["pip", "index", "versions", PACKAGE_NAME, "--json"],
            capture_output=True,
            text=True,
            timeout=5.0,
        )

        if result.returncode != 0:
            return

        # Parse JSON output
        data = json.loads(result.stdout)
        available_versions = data.get("versions", [])
        latest_version_str = data.get("latest")

        if not latest_version_str or not available_versions:
            return

        latest_version = version.parse(latest_version_str)

        # Check if current version is yanked/deprecated
        # A version is considered yanked if:
        # 1. It's not in the available versions list, AND
        # 2. It's smaller than the latest version
        is_yanked = (
            current_version_str not in available_versions
            and current_version < latest_version
        )

        if is_yanked:
            stderr_console.print(
                f"[bold orange1]Warning:[/bold orange1] Currently used {PACKAGE_NAME} "
                f"version {current_version} is yanked/deprecated. "
                f"You should update to a newer version. Update via `pip install -U labtasker`."
            )

        # Check for newer version
        if latest_version > current_version:
            stdout_console.print(
                f"[bold sea_green3]Tip:[/bold sea_green3] {PACKAGE_NAME} has a new version "
                f"available! Current: {current_version}, newest: {latest_version}. Update via `pip install -U labtasker`."
            )

    except Exception:
        # Silently handle all exceptions
        pass


def check_package_version(force_check: bool = False, blocking: bool = False) -> None:
    """Run the package version check in a thread or directly"""
    global _process_checked

    # Check if a thread is already running
    thread = _check_thread.get()
    if thread and thread.is_alive():
        if blocking:  # wait for the thread to finish
            thread.join()
        return

    # Check if a check is needed
    if not force_check and not should_check():
        return

    _process_checked = True
    update_last_checked()

    new_thread = threading.Thread(target=_check_pip_versions, daemon=True)
    _check_thread.set(new_thread)
    new_thread.start()

    if blocking:  # wait for the thread to finish
        new_thread.join()
