from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Annotated, Any, TypeVar, cast

import typer
from pydantic import BaseModel
from typer._click.core import Context as ClickContext
from typer.core import TyperCommand

from labtasker import __version__
from labtasker.client import Client
from labtasker.command_template import TemplateSyntaxError
from labtasker.command_worker import run_command_worker
from labtasker.config import resolve_config
from labtasker.errors import LabtaskerError
from labtasker.types import TaskOrderField, TaskStatus, TaskUpdate
from labtasker.validation import RequestValidationError, validate_json_object

T = TypeVar("T")
app = typer.Typer(
    help="Submit, inspect, and execute Labtasker v2 Tasks.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
)
task_app = typer.Typer(
    help="Submit, inspect, update, and control Tasks.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
)
queue_app = typer.Typer(
    help="Create, list, and delete Queue namespaces.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
)
config_app = typer.Typer(
    help="Inspect the resolved Client configuration.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
)
app.add_typer(task_app, name="task")
app.add_typer(queue_app, name="queue")
app.add_typer(config_app, name="config")
logger = logging.getLogger("labtasker.cli")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"labtasker-client {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the Client package version and exit.",
        ),
    ] = False,
) -> None:
    """Submit, inspect, and execute Labtasker v2 Tasks."""


class _SeparatedCommand(TyperCommand):
    """Require the explicit boundary between Worker options and child argv."""

    def collect_usage_pieces(self, ctx: ClickContext) -> list[str]:
        return [*super().collect_usage_pieces(ctx), "--", "COMMAND", "[ARG...]"]

    def parse_args(self, ctx: ClickContext, args: list[str]) -> list[str]:
        ctx.meta["labtasker_command_separator"] = "--" in args
        return super().parse_args(ctx, args)


@app.command(
    "loop",
    cls=_SeparatedCommand,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def worker_loop(
    context: typer.Context,
    route: Annotated[
        str,
        typer.Option(help="Exact route claimed by this Worker."),
    ] = "default",
    queue: Annotated[
        str | None,
        typer.Option(help="Queue to claim from; otherwise use Client configuration."),
    ] = None,
    idle_timeout: Annotated[
        float,
        typer.Option(help="Seconds without an eligible Task before normal exit."),
    ] = 300.0,
    force_stop_timeout: Annotated[
        float | None,
        typer.Option(
            help=(
                "Seconds to wait after run revocation before killing the child; "
                "wait forever if omitted."
            )
        ),
    ] = None,
) -> None:
    """Claim matching Tasks and execute one child command for each claim.

    The explicit -- separator is required. Everything after it is one argv
    template; Labtasker never invokes a shell or re-splits arguments. %{name}
    reads a Task argument, and %{object.field} traverses nested JSON objects.

    Example:

    \b
      labtasker loop --route train -- \\
        python train.py --seed '%{seed}' --lr '%{optimizer.lr}'
    """
    if not context.meta.get("labtasker_command_separator", False):
        raise typer.BadParameter("COMMAND is required after --")
    argv = list(context.args)
    if argv and argv[0] == "--":
        argv.pop(0)
    if not argv:
        raise typer.BadParameter("COMMAND is required after --")
    try:
        run_command_worker(
            argv,
            route=route,
            queue=queue,
            idle_timeout=idle_timeout,
            force_stop_timeout=force_stop_timeout,
        )
    except (TemplateSyntaxError, RequestValidationError) as error:
        raise typer.BadParameter(str(error)) from error
    except NotImplementedError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    except LabtaskerError as error:
        typer.echo(f"{error.code}: {error.message}", err=True)
        raise typer.Exit(1) from error
    except KeyboardInterrupt:
        raise
    except Exception as error:
        logger.error("Worker stopped: %s", error)
        raise typer.Exit(1) from error


@task_app.command("submit")
def task_submit(
    args: Annotated[
        str,
        typer.Option(help="Task arguments as one strict JSON object."),
    ] = "{}",
    name: Annotated[
        str | None,
        typer.Option(help="Optional human-readable Task name."),
    ] = None,
    metadata: Annotated[
        str,
        typer.Option(help="Searchable metadata as one strict JSON object."),
    ] = "{}",
    priority: Annotated[
        int,
        typer.Option(help="Claim higher priorities first."),
    ] = 0,
    max_attempts: Annotated[
        int,
        typer.Option(min=1, help="Maximum number of charged execution attempts."),
    ] = 3,
    routes: Annotated[
        list[str] | None,
        typer.Option("--route", help="Compatible exact route; repeat for multiple routes."),
    ] = None,
    task_id: Annotated[
        str | None,
        typer.Option("--id", help="Caller-chosen idempotent Task ID."),
    ] = None,
    queue: Annotated[
        str | None,
        typer.Option(help="Target Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """Submit one Task and print its complete representation as JSON.

    JSON types are preserved exactly; the CLI never guesses types from text.
    --route defaults to default when omitted.

    Example:

    \b
      labtasker task submit --name baseline \\
        --args '{"seed":1,"enabled":true}' \\
        --metadata '{"group":"paper"}' --route train
    """
    result = _invoke(
        lambda: _with_client(
            lambda client: client.submit_task(
                _json_object(args, option="--args"),
                name=name,
                metadata=_json_object(metadata, option="--metadata"),
                priority=priority,
                max_attempts=max_attempts,
                routes=routes,
                task_id=task_id,
                queue=queue,
            )
        )
    )
    _write_json(result)


@task_app.command("get")
def task_get(
    task_id: Annotated[str, typer.Argument(help="Task ID to retrieve.")],
    queue: Annotated[
        str | None,
        typer.Option(help="Task Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """Get one Task by ID and print its complete representation as JSON."""
    _write_json(_invoke(lambda: _with_client(lambda client: client.get_task(task_id, queue=queue))))


@task_app.command("list")
def task_list(
    status: Annotated[
        TaskStatus | None,
        typer.Option(help="Select exactly one lifecycle status."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option(help="Select an exact Task name; empty string is valid."),
    ] = None,
    filter: Annotated[
        str | None,
        typer.Option(help="Additional Task query expression."),
    ] = None,
    order_by: Annotated[
        TaskOrderField,
        typer.Option(help="Stable field used to order this page."),
    ] = "created_at",
    descending: Annotated[
        bool,
        typer.Option("--descending/--ascending", help="Choose ordering direction."),
    ] = True,
    limit: Annotated[
        int,
        typer.Option(min=1, max=1000, help="Maximum Tasks in this page."),
    ] = 100,
    cursor: Annotated[
        str | None,
        typer.Option(help="Opaque next_cursor from the same query and ordering."),
    ] = None,
    queue: Annotated[
        str | None,
        typer.Option(help="Task Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """List one page of Tasks and print items plus next_cursor as JSON.

    --status, --name, and --filter are combined with logical AND.
    Reuse a returned cursor only with the same selectors and ordering.

    Example:

    \b
      labtasker task list --status pending \\
        --filter 'priority >= 10 and metadata.group == "paper"' \\
        --order-by priority --descending --limit 100
    """
    result = _invoke(
        lambda: _with_client(
            lambda client: client.list_tasks(
                status=status,
                name=name,
                filter=filter,
                order_by=order_by,
                descending=descending,
                limit=limit,
                cursor=cursor,
                queue=queue,
            )
        )
    )
    _write_json(result)


@task_app.command("count")
def task_count(
    status: Annotated[
        TaskStatus | None,
        typer.Option(help="Select exactly one lifecycle status."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option(help="Select an exact Task name; empty string is valid."),
    ] = None,
    filter: Annotated[
        str | None,
        typer.Option(help="Additional Task query expression."),
    ] = None,
    queue: Annotated[
        str | None,
        typer.Option(help="Task Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """Count Tasks matching all supplied selectors and print JSON.

    Example:

    \b
      labtasker task count --status failed \\
        --filter 'last_error.type == "ValueError"'
    """
    count = _invoke(
        lambda: _with_client(
            lambda client: client.count_tasks(
                status=status,
                name=name,
                filter=filter,
                queue=queue,
            )
        )
    )
    _write_json({"count": count})


@task_app.command("update")
def task_update(
    task_id: Annotated[
        str | None,
        typer.Argument(help="One Task ID; mutually exclusive with --filter."),
    ] = None,
    filter: Annotated[
        str | None,
        typer.Option(help="Atomically select many Tasks; mutually exclusive with TASK_ID."),
    ] = None,
    changes: Annotated[
        str,
        typer.Option(help="Fields to replace as one strict JSON object."),
    ] = "",
    queue: Annotated[
        str | None,
        typer.Option(help="Task Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """Update one Task by ID or all Tasks matching a query.

    Provide exactly one of TASK_ID and --filter. --changes replaces
    every supplied field in full; unspecified fields remain unchanged. Running
    Tasks cannot be updated. A batch update is one atomic Server operation.

    Examples:

    \b
      labtasker task update t_ABCDEFGHIJKL \\
        --changes '{"priority":20}'
      labtasker task update --filter 'status == "pending"' \\
        --changes '{"routes":["train-v2"]}'
    """
    if (task_id is None) == (filter is None):
        raise typer.BadParameter("provide exactly one of TASK_ID or --filter")
    if not changes:
        raise typer.BadParameter("--changes is required")
    normalized = cast(TaskUpdate, _json_object(changes, option="--changes"))
    result: object
    if task_id is not None:
        result = _invoke(
            lambda: _with_client(
                lambda client: client.update_task(task_id, normalized, queue=queue)
            )
        )
    else:
        result = _invoke(
            lambda: _with_client(
                lambda client: client.update_tasks(
                    filter=filter or "",
                    changes=normalized,
                    queue=queue,
                )
            )
        )
    _write_json(result)


@task_app.command("cancel")
def task_cancel(
    task_id: Annotated[str, typer.Argument(help="Task ID to cancel.")],
    queue: Annotated[
        str | None,
        typer.Option(help="Task Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """Cancel a pending or running Task and print its new state as JSON.

    Cancelling a running Task revokes its current run immediately on the Server;
    local shutdown follows the Worker's cooperative or force-stop policy.
    """
    _write_json(
        _invoke(lambda: _with_client(lambda client: client.cancel_task(task_id, queue=queue)))
    )


@task_app.command("requeue")
def task_requeue(
    task_id: Annotated[str, typer.Argument(help="Non-running Task ID to requeue.")],
    queue: Annotated[
        str | None,
        typer.Option(help="Task Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """Return a non-running Task to pending and reset its attempt count."""
    _write_json(
        _invoke(lambda: _with_client(lambda client: client.requeue_task(task_id, queue=queue)))
    )


@task_app.command("delete")
def task_delete(
    task_id: Annotated[str, typer.Argument(help="Non-running Task ID to delete.")],
    queue: Annotated[
        str | None,
        typer.Option(help="Task Queue; otherwise use Client configuration."),
    ] = None,
) -> None:
    """Permanently delete one non-running Task.

    Success is quiet. This operation cannot be undone.
    """
    _invoke(lambda: _with_client(lambda client: client.delete_task(task_id, queue=queue)))


@queue_app.command("create")
def queue_create(name: Annotated[str, typer.Argument(help="Queue name to create.")]) -> None:
    """Create a Queue, or return the existing Queue with the same name."""
    _write_json(_invoke(lambda: _with_client(lambda client: client.create_queue(name))))


@queue_app.command("list")
def queue_list() -> None:
    """List all Queue namespaces as formatted JSON."""
    _write_json(_invoke(lambda: _with_client(lambda client: client.list_queues())))


@queue_app.command("delete")
def queue_delete(
    name: Annotated[str, typer.Argument(help="Queue name to delete.")],
    cascade: Annotated[
        bool,
        typer.Option(help="Also permanently delete every non-running Task in the Queue."),
    ] = False,
) -> None:
    """Permanently delete one Queue.

    A non-empty Queue requires explicit --cascade. A Queue containing a
    running Task cannot be deleted. Success is quiet.
    """
    _invoke(lambda: _with_client(lambda client: client.delete_queue(name, cascade=cascade)))


@config_app.command("show")
def config_show() -> None:
    """Print the effective URL, Queue, and non-secret token presence as JSON.

    Resolution precedence is explicit arguments, environment, project-local
    .labtasker/config.toml, then built-in defaults. The token value is never
    printed.
    """
    _write_json(_invoke(lambda: resolve_config().public_dict()))


def _with_client(operation: Callable[[Client], T]) -> T:
    with Client() as client:
        return operation(client)


def _invoke(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except LabtaskerError as error:
        _write_json(error.as_envelope())
        raise typer.Exit(1) from error
    except RequestValidationError as error:
        raise typer.BadParameter(str(error)) from error


def _json_object(value: str, *, option: str) -> dict[str, Any]:
    def reject_constant(constant: str) -> None:
        raise ValueError(f"non-standard number {constant}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ValueError(f"duplicate key {key!r}")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value,
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
        return validate_json_object(parsed, field=option)
    except (json.JSONDecodeError, ValueError, RequestValidationError) as error:
        raise typer.BadParameter(f"{option} must be one strict JSON object: {error}") from error


def _write_json(value: object) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list) and all(isinstance(item, BaseModel) for item in value):
        value = [item.model_dump(mode="json") for item in value]
    typer.echo(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        nl=False,
    )
