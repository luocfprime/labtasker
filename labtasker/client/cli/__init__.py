import labtasker.client.cli.config
from labtasker.client.cli.cli import app
from labtasker.client.cli.queue import app as queue_app

app.add_typer(queue_app, name="queue")
