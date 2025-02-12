import labtasker.client.cli.config
from labtasker.client.cli.cli import app
from labtasker.client.cli.queue import app as queue_app
from labtasker.client.cli.task import app as task_app
from labtasker.client.cli.worker import app as worker_app

app.add_typer(queue_app, name="queue")
app.add_typer(task_app, name="task")
app.add_typer(worker_app, name="worker")
