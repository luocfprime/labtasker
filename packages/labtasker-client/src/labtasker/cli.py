from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Annotated, Any, TypeVar, cast

import typer
from pydantic import BaseModel
from typer.core import TyperCommand

from labtasker import __version__
from labtasker.client import Client
from labtasker.command_template import TemplateSyntaxError
from labtasker.command_worker import run_command_worker
from labtasker.config import resolve_config
from labtasker.errors import LabtaskerError
from labtasker.execution import report_progress as report_current_progress
from labtasker.execution import report_worker_telemetry as report_current_worker_telemetry
from labtasker.types import TaskOrderField, TaskStatus, TaskUpdate
from labtasker.validation import RequestValidationError, validate_grouping, validate_json_object

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
worker_app = typer.Typer(
    help="Inspect online Worker observations.",
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,
)
app.add_typer(worker_app, name="worker")
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

    # Typer 0.26 vendored Click, so its internal Context type differs from the
    # public typer.Context used by earlier supported releases.
    def collect_usage_pieces(self, ctx: Any) -> list[str]:
        return [*super().collect_usage_pieces(ctx), "--", "COMMAND", "[ARG...]"]

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
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
    max_consecutive_failures: Annotated[
        int,
        typer.Option(
            help="Stop after this many consecutive execution failures (positive integer)."
        ),
    ] = 5,
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
    metadata: Annotated[
        str,
        typer.Option(help="Static Worker metadata as one strict JSON object."),
    ] = "{}",
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
    worker_metadata = _json_object(metadata, option="--metadata")
    try:
        run_command_worker(
            argv,
            route=route,
            queue=queue,
            idle_timeout=idle_timeout,
            max_consecutive_failures=max_consecutive_failures,
            force_stop_timeout=force_stop_timeout,
            metadata=worker_metadata,
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


@app.command("progress")
def progress_report(
    data: Annotated[
        str,
        typer.Option(help="Latest progress as one strict JSON object."),
    ],
) -> None:
    """Replace the current Task run's progress snapshot.

    This command is available inside a command launched by ``labtasker loop``.
    It prints whether the best-effort report was accepted; transport failures
    and confirmed revocation return ``reported: false`` without failing the
    command workload.
    """
    try:
        progress = _json_object(data, option="--data")
        reported = _invoke(lambda: report_current_progress(progress))
    except RuntimeError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    _write_json({"reported": reported})


@task_app.command("submit")
def task_submit(
    args: Annotated[
        str,
        typer.Option(metavar="<str>", help="Task arguments as one strict JSON object."),
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
    name_fuzzy: Annotated[
        str | None,
        typer.Option(help="Case-insensitive subsequence search; every word must match."),
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

    --status, --name, --name-fuzzy, and --filter are combined with logical AND.
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
                name_fuzzy=name_fuzzy,
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
    name_fuzzy: Annotated[
        str | None,
        typer.Option(help="Case-insensitive subsequence search; every word must match."),
    ] = None,
    filter: Annotated[
        str | None,
        typer.Option(help="Additional Task query expression."),
    ] = None,
    group_by: Annotated[
        list[str] | None,
        typer.Option(
            "--group-by",
            help=(
                "Comma-separated grouping fields, with no spaces "
                "(for example: routes,status). Supported fields: routes, status. Specify once."
            ),
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            min=1, max=1000, help="Maximum groups in this page (default 100); requires --group-by."
        ),
    ] = None,
    cursor: Annotated[
        str | None, typer.Option(help="Next group page cursor; requires --group-by.")
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
    count_options = _invoke(lambda: _count_options(group_by, {"routes", "status"}, limit, cursor))
    count = _invoke(
        lambda: _with_client(
            lambda client: client.count_tasks(
                status=status,
                name=name,
                name_fuzzy=name_fuzzy,
                filter=filter,
                queue=queue,
                **count_options,
            )
        )
    )
    _write_json({"count": count} if isinstance(count, int) else count)


@worker_app.command("list")
def worker_list(
    filter: Annotated[str | None, typer.Option(help="Worker filter expression.")] = None,
    limit: Annotated[
        int, typer.Option(min=1, max=1000, help="Maximum Workers in this page.")
    ] = 100,
    cursor: Annotated[
        str | None, typer.Option(help="Next cursor from the same Worker query.")
    ] = None,
    queue: Annotated[
        str | None, typer.Option(help="Queue; otherwise use Client configuration.")
    ] = None,
) -> None:
    """List one page of unexpired Worker observations as JSON, ordered by ID."""
    _write_json(
        _invoke(
            lambda: _with_client(
                lambda client: client.list_workers(
                    filter=filter, limit=limit, cursor=cursor, queue=queue
                )
            )
        )
    )


@worker_app.command("count")
def worker_count(
    filter: Annotated[str | None, typer.Option(help="Worker filter expression.")] = None,
    group_by: Annotated[
        list[str] | None,
        typer.Option(
            "--group-by",
            help=(
                "Comma-separated grouping fields, with no spaces "
                "(for example: route,status). Supported fields: route, status. Specify once."
            ),
        ),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option(
            min=1, max=1000, help="Maximum groups in this page (default 100); requires --group-by."
        ),
    ] = None,
    cursor: Annotated[
        str | None, typer.Option(help="Next group page cursor; requires --group-by.")
    ] = None,
    queue: Annotated[
        str | None, typer.Option(help="Queue; otherwise use Client configuration.")
    ] = None,
) -> None:
    """Count unexpired Worker observations, optionally grouped, as JSON."""
    options = _invoke(lambda: _count_options(group_by, {"route", "status"}, limit, cursor))
    result = _invoke(
        lambda: _with_client(
            lambda client: client.count_workers(filter=filter, queue=queue, **options)
        )
    )
    _write_json({"count": result} if isinstance(result, int) else result)


@worker_app.command("telemetry")
def worker_telemetry_report(
    data: Annotated[
        str,
        typer.Option(help="Latest Worker telemetry as one strict JSON object."),
    ],
) -> None:
    """Replace telemetry for the current Worker invocation.

    This command is available inside a command launched by ``labtasker loop``.
    It performs one best-effort synchronous report and prints whether the Server
    accepted it.
    """
    try:
        telemetry = _json_object(data, option="--data")
        reported = _invoke(lambda: report_current_worker_telemetry(telemetry))
    except RuntimeError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    _write_json({"reported": reported})


def _count_options(
    group_by: list[str] | None, allowed: set[str], limit: int | None, cursor: str | None
) -> dict[str, Any]:
    if group_by is not None and len(group_by) != 1:
        raise RequestValidationError("Specify --group-by only once, comma-separated with no spaces")
    value = None if group_by is None else group_by[0].split(",")
    fields = validate_grouping(value, allowed, limit, cursor)
    if fields is None:
        return {}
    return {"group_by": fields, "limit": limit, "cursor": cursor}


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
    except (json.JSONDecodeError, ValueError, RequestValidationError, RecursionError) as error:
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
