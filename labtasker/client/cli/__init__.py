from labtasker.client.cli.cli import app
from labtasker.client.cli.config import app as config_app

app.add_typer(config_app, name="config")
