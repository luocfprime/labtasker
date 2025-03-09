import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import typer
from packaging import version

from labtasker import __version__
from labtasker.client.core.config import get_client_config
from labtasker.client.core.logging import stderr_console, stdout_console

try:
    _should_check = get_client_config().version_check
except typer.Exit:  # config not initialized
    _should_check = True  # default to True


_checked = False


def _check_pypi_status():
    """Check PyPI status"""
    package_name = "labtasker"
    current_version = version.parse(__version__)

    try:
        response = httpx.get(f"https://pypi.org/pypi/{package_name}/json", timeout=5.0)
        if response.status_code != 200:
            return

        data = response.json()
        releases = data.get("releases", {})

        parsed_releases = {version.parse(k): v for k, v in releases.items()}

        # check if current version is yanked
        if current_version in parsed_releases:
            release_info = parsed_releases[current_version]
            if release_info and all(file.get("yanked", False) for file in release_info):
                stderr_console.print(
                    f"[bold orange1]Warning:[/bold orange1] Currently used {package_name} version {current_version} is yanked/deprecated. "
                    f"You should update to a newer version.",
                )

        # check for newer version
        all_versions = sorted(releases.keys(), reverse=True)
        newest_version = version.parse(all_versions[0]) if all_versions else None
        if newest_version and newest_version > current_version:
            stdout_console.print(
                f"[bold sea_green3]Tip:[/bold sea_green3] {package_name} has a new version available! Current: {current_version}, newest: {newest_version}."
            )

    except Exception:
        # silently handle all exceptions
        pass


def check_pypi_status(blocking: bool = False):
    """Run the PyPI status check in a thread pool"""
    global _checked
    if not _should_check or _checked:
        return

    _checked = True

    if blocking:
        _check_pypi_status()
        return

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_check_pypi_status)

    # Use a daemon thread to avoid blocking main process exit
    thread = threading.Thread(target=future.result, daemon=True)
    thread.start()
