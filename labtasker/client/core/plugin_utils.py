import fnmatch
import importlib
import sys
from typing import List

from labtasker.client.core.config import PluginConfig
from labtasker.client.core.logging import logger, stderr_console

if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points


def package_name(module_name):
    return module_name.split(".")[0]


def match(name, pattern):
    return fnmatch.fnmatch(name, pattern)


def matches_patterns(name: str, patterns: List[str]) -> bool:
    """
    Checks if a name matches any of the provided wildcard patterns.

    Args:
        name: The string to check against the patterns.
        patterns: A list of wildcard patterns (e.g., ['plugin_*', 'test?']).

    Returns:
        True if the name matches any pattern; False otherwise.
    """
    logger.debug(f"Checking if '{name}' matches any of the patterns: {patterns}")
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def load_plugins(group, config: PluginConfig):
    discovered_entry_points = entry_points(group=group)
    plugins = {}  # Map: package name -> plugin module

    # Collect all plugins
    for entry_point in discovered_entry_points:
        plugins[package_name(entry_point.module)] = entry_point.module

    # Filter plugins based on configuration
    loaded_plugins = {}
    for package, module in plugins.items():
        if config.default == "all":
            # Exclude plugins matching wildcard patterns in `exclude`
            if not matches_patterns(package, config.exclude):
                loaded_plugins[package] = module
            else:
                logger.debug(f"Excluding plugin '{package}'")
        elif config.default == "selected":
            # Include only plugins matching wildcard patterns in `include`
            if matches_patterns(package, config.include):
                loaded_plugins[package] = module
            else:
                logger.debug(f"Excluding plugin '{package}'")

    # Import the filtered plugins
    for package, module in loaded_plugins.items():
        try:
            importlib.import_module(module)
            logger.debug(f"Successfully loaded plugin '{package}' from '{module}'")
        except Exception as e:
            stderr_console.print(
                f"[bold orange1]Warning:[/bold orange1] Error loading custom CLI plugin '{package}' from '{module}'\n"
                f"Detail: {e}"
            )
            logger.debug(f"Error loading custom CLI plugin '{package}' from '{module}'")
