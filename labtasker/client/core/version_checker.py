import threading
from contextvars import ContextVar
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx
import typer
from packaging import version

from labtasker import __version__
from labtasker.client.core.config import get_client_config
from labtasker.client.core.logging import stderr_console, stdout_console
from labtasker.client.core.paths import get_labtasker_root
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
    try:
        return get_client_config().version_check
    except typer.Exit:  # config not initialized
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


def _check_pypi_status() -> None:
    """Check PyPI for version updates or yanked status"""
    current_version = version.parse(__version__)

    try:
        response = httpx.get(f"https://pypi.org/pypi/{PACKAGE_NAME}/json", timeout=5.0)
        if response.status_code != 200:
            return

        data = response.json()
        releases = data.get("releases", {})
        parsed_releases = {version.parse(k): v for k, v in releases.items()}

        # Check if current version is yanked
        if current_version in parsed_releases:
            release_info = parsed_releases[current_version]
            if release_info and all(file.get("yanked", False) for file in release_info):
                stderr_console.print(
                    f"[bold orange1]Warning:[/bold orange1] Currently used {PACKAGE_NAME} "
                    f"version {current_version} is yanked/deprecated. "
                    f"You should update to a newer version. Update via `pip install -U labtasker`."
                )

        # Check for newer version
        all_versions = sorted(
            (version.parse(ver) for ver in releases.keys()), reverse=True
        )

        if all_versions and all_versions[0] > current_version:
            stdout_console.print(
                f"[bold sea_green3]Tip:[/bold sea_green3] {PACKAGE_NAME} has a new version "
                f"available! Current: {current_version}, newest: {all_versions[0]}. Update via `pip install -U labtasker`."
            )

    except Exception:
        # Silently handle all exceptions
        pass


def check_pypi_status(force_check: bool = False, blocking: bool = False) -> None:
    """Run the PyPI status check in a thread or directly"""
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

    new_thread = threading.Thread(target=_check_pypi_status, daemon=True)
    _check_thread.set(new_thread)
    new_thread.start()

    if blocking:  # wait for the thread to finish
        new_thread.join()
