import importlib
import sys

from labtasker.client.core.logging import stderr_console

if sys.version_info < (3, 10):
    from importlib_metadata import entry_points
else:
    from importlib.metadata import entry_points


def load_cli_plugins():
    discovered_entry_points = entry_points(group="labtasker.client.cli")

    for entry_point in discovered_entry_points:
        try:
            importlib.import_module(entry_point.module)
        except Exception as e:
            stderr_console.print(
                f"[bold orange1]Warning:[/bold orange1] Error loading custom CLI plugin '{entry_point.module}'\n"
                f"Detail: {e}"
            )
