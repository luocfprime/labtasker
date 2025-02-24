# 1 level commands
import labtasker.client.cli.config
import labtasker.client.cli.loop

# multi level commands
import labtasker.client.cli.queue as queue
import labtasker.client.cli.task as task
import labtasker.client.cli.worker as worker
from labtasker.client.cli.cli import app
from labtasker.client.core.config import get_client_config
from labtasker.client.core.logging import stderr_console
from labtasker.client.core.paths import get_labtasker_client_config_path
from labtasker.client.core.plugin_utils import load_plugins

app.add_typer(queue.app, name="queue", help=queue.__doc__)
app.add_typer(task.app, name="task", help=task.__doc__)
app.add_typer(worker.app, name="worker", help=task.__doc__)

if get_labtasker_client_config_path().exists():
    load_plugins(group="labtasker.client.cli", config=get_client_config().cli_plugins)
else:
    stderr_console.print(
        f"[bold orange1]Warning:[/bold orange1] config file not found at {get_labtasker_client_config_path()}. "
        f"[orange1]Skipped plugin loading.[/orange1] "
        f"It is recommended to initialize config via running [orange1]`labtasker config`[/orange1] first."
    )
