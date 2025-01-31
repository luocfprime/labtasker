from loguru import logger  # noqa
from rich.console import Console

stdout_console = Console(markup=True)
stderr_console = Console(markup=True, stderr=True)
