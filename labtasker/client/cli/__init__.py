import labtasker.client.cli.config
import labtasker.client.cli.loop

# sub commands
import labtasker.client.cli.queue as queue
import labtasker.client.cli.task as task
import labtasker.client.cli.worker as worker
from labtasker.client.cli.cli import app

app.add_typer(queue.app, name="queue", help=queue.__doc__)
app.add_typer(task.app, name="task", help=task.__doc__)
app.add_typer(worker.app, name="worker", help=task.__doc__)
