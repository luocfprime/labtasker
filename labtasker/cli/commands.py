import json
from importlib import metadata
from typing import Optional

import click

from ..client import Tasker


@click.group()
def cli():
    """Labtasker CLI - A task queue system for lab experiments"""
    pass


# Register built-in commands
def load_commands():
    """Load commands from entry points"""
    try:
        # For Python 3.10+
        entry_points = metadata.entry_points().select(group="labtasker.commands")
    except AttributeError:
        # For older Python versions
        entry_points = metadata.entry_points().get("labtasker.commands", [])

    for entry_point in entry_points:
        command = entry_point.load()
        if isinstance(command, click.Command):
            cli.add_command(command)
        else:
            cli.add_command(command, name=entry_point.name)


# Define commands as standalone Click commands
@click.command()
@click.option(
    "--client-config",
    required=True,
    help="Path to client configuration file",
)
def config(client_config):
    """Create or validate client configuration"""
    try:
        tasker = Tasker(client_config)
        click.echo("Configuration validated successfully!")
        click.echo(f"Server: {tasker.server_address}")
        click.echo(f"Queue: {tasker.queue_name}")
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)


@click.command()
@click.option(
    "--client-config",
    required=True,
    help="Path to client configuration file",
)
def create_queue(client_config):
    """Create a new task queue"""
    try:
        tasker = Tasker(client_config)
        status, queue_id = tasker.create_queue()
        if status == "success":
            click.echo(
                json.dumps(
                    {
                        "status": "success",
                        "queue_name": tasker.queue_name,
                        "queue_id": queue_id,
                    },
                    indent=2,
                )
            )
        else:
            click.echo(f"Error: {queue_id}", err=True)
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)


@click.command()
@click.option(
    "--client-config",
    required=True,
    help="Path to client configuration file",
)
@click.option("--task-name", required=True, help="Name of the task")
@click.option("--args", required=True, help="Task arguments as JSON string")
@click.option("--metadata", help="Task metadata as JSON string")
def submit(client_config, task_name, args, metadata):
    """Submit a task to the queue"""
    try:
        tasker = Tasker(client_config)
        args_dict = json.loads(args)
        metadata_dict = json.loads(metadata) if metadata else None

        status, task_id = tasker.submit(
            task_name=task_name,
            args=args_dict,
            metadata=metadata_dict,
        )

        if status == "success":
            click.echo(json.dumps({"status": "success", "task_id": task_id}, indent=2))
        else:
            click.echo(f"Error: {task_id}", err=True)
    except json.JSONDecodeError:
        click.echo("Error: Invalid JSON format in args or metadata", err=True)
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)


@click.command()
@click.option(
    "--client-config",
    required=True,
    help="Path to client configuration file",
)
@click.option(
    "--eta-max",
    default="2h",
    help='Maximum execution time (e.g., "2h", "30m")',
)
def fetch(client_config, eta_max):
    """Fetch a task from the queue"""
    try:
        tasker = Tasker(client_config)
        result = tasker.fetch(eta_max=eta_max)
        click.echo(json.dumps(result, indent=2))
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)


@click.command()
@click.option("--client-config", required=True, help="Path to client config file")
@click.option("--task-id", help="Filter by task ID")
@click.option("--task-name", help="Filter by task name")
@click.option("--queue-id", help="Queue ID to get tasks from")
@click.option("--queue-name", help="Queue name to get tasks from")
def get_task(
    client_config: str,
    task_id: Optional[str],
    task_name: Optional[str],
    queue_id: Optional[str],
    queue_name: Optional[str],
):
    """Get tasks matching the criteria."""
    try:
        client = Tasker(client_config=client_config)
        if not queue_name:
            queue_name = client.queue_name
        tasks = client.get_tasks(
            task_id=task_id,
            task_name=task_name,
            queue_id=queue_id,
            queue_name=queue_name,
        )
        click.echo(json.dumps(tasks, indent=2))
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Abort()


@click.command()
@click.option("--client-config", required=True, help="Path to client config file")
@click.option("--queue-id", help="Queue ID to get tasks from")
@click.option("--queue-name", help="Queue name to get tasks from")
@click.option("--status", help="Filter by task status")
@click.option("--tag", help="Filter by tag in metadata")
def ls_tasks(
    client_config: str,
    queue_id: str = None,
    queue_name: str = None,
    status: str = None,
    tag: str = None,
):
    """Get list of tasks from a queue."""
    if not queue_id and not queue_name:
        click.echo(
            "Error: Either --queue-id or --queue-name must be provided", err=True
        )
        raise click.Abort()

    try:
        client = Tasker(client_config=client_config)
        tasks = client.get_tasks(
            queue_id=queue_id, queue_name=queue_name, status=status, tag=tag
        )
        click.echo(json.dumps(tasks, indent=2))
    except FileNotFoundError as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Abort()
    except Exception as e:
        click.echo(f"Error: Failed to get tasks - {str(e)}", err=True)
        raise click.Abort()


# Register commands
cli.add_command(config)
cli.add_command(create_queue)
cli.add_command(submit)
cli.add_command(fetch)
cli.add_command(get_task)
cli.add_command(ls_tasks)

# Load plugin commands
load_commands()

if __name__ == "__main__":
    cli()
