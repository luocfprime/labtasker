from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Annotated, Any, TypeVar, cast

import typer
from pydantic import BaseModel
from typer._click.core import Context as ClickContext
from typer.core import TyperCommand

from labtasker.client import Client
from labtasker.command_template import TemplateSyntaxError
from labtasker.command_worker import run_command_worker
from labtasker.config import resolve_config
from labtasker.errors import LabtaskerError
from labtasker.types import TaskOrderField, TaskStatus, TaskUpdate
from labtasker.validation import RequestValidationError, validate_json_object

T = TypeVar("T")
app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    rich_markup_mode=None,
)
task_app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode=None)
queue_app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode=None)
config_app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode=None)
app.add_typer(task_app, name="task")
app.add_typer(queue_app, name="queue")
app.add_typer(config_app, name="config")
logger = logging.getLogger("labtasker.cli")


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
    route: Annotated[str, typer.Option()] = "default",
    queue: Annotated[str | None, typer.Option()] = None,
    idle_timeout: Annotated[float, typer.Option()] = 300.0,
    force_stop_timeout: Annotated[float | None, typer.Option()] = None,
) -> None:
    """Claim Tasks and execute one command for each claim."""
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
    except LabtaskerError as error:
        logger.error("%s: %s", error.code, error.message)
        raise typer.Exit(1) from error
    except KeyboardInterrupt:
        raise
    except Exception as error:
        logger.error("Worker stopped: %s", error)
        raise typer.Exit(1) from error


@task_app.command("submit")
def task_submit(
    args: Annotated[str, typer.Option(help="Strict JSON object.")] = "{}",
    name: Annotated[str | None, typer.Option()] = None,
    metadata: Annotated[str, typer.Option(help="Strict JSON object.")] = "{}",
    priority: Annotated[int, typer.Option()] = 0,
    max_attempts: Annotated[int, typer.Option(min=1)] = 3,
    routes: Annotated[list[str] | None, typer.Option("--route")] = None,
    task_id: Annotated[str | None, typer.Option("--id")] = None,
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
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
    task_id: Annotated[str, typer.Argument()],
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
    _write_json(_invoke(lambda: _with_client(lambda client: client.get_task(task_id, queue=queue))))


@task_app.command("list")
def task_list(
    status: Annotated[TaskStatus | None, typer.Option()] = None,
    name: Annotated[str | None, typer.Option()] = None,
    filter: Annotated[str | None, typer.Option()] = None,
    order_by: Annotated[TaskOrderField, typer.Option()] = "created_at",
    descending: Annotated[bool, typer.Option("--descending/--ascending")] = True,
    limit: Annotated[int, typer.Option(min=1, max=1000)] = 100,
    cursor: Annotated[str | None, typer.Option()] = None,
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
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
    status: Annotated[TaskStatus | None, typer.Option()] = None,
    name: Annotated[str | None, typer.Option()] = None,
    filter: Annotated[str | None, typer.Option()] = None,
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
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
    task_id: Annotated[str | None, typer.Argument()] = None,
    filter: Annotated[str | None, typer.Option()] = None,
    changes: Annotated[str, typer.Option(help="Strict JSON object.")] = "",
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
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
    task_id: Annotated[str, typer.Argument()],
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
    _write_json(
        _invoke(lambda: _with_client(lambda client: client.cancel_task(task_id, queue=queue)))
    )


@task_app.command("requeue")
def task_requeue(
    task_id: Annotated[str, typer.Argument()],
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
    _write_json(
        _invoke(lambda: _with_client(lambda client: client.requeue_task(task_id, queue=queue)))
    )


@task_app.command("delete")
def task_delete(
    task_id: Annotated[str, typer.Argument()],
    queue: Annotated[str | None, typer.Option()] = None,
) -> None:
    _invoke(lambda: _with_client(lambda client: client.delete_task(task_id, queue=queue)))


@queue_app.command("create")
def queue_create(name: Annotated[str, typer.Argument()]) -> None:
    _write_json(_invoke(lambda: _with_client(lambda client: client.create_queue(name))))


@queue_app.command("list")
def queue_list() -> None:
    _write_json(_invoke(lambda: _with_client(lambda client: client.list_queues())))


@queue_app.command("delete")
def queue_delete(
    name: Annotated[str, typer.Argument()],
    cascade: Annotated[bool, typer.Option()] = False,
) -> None:
    _invoke(lambda: _with_client(lambda client: client.delete_queue(name, cascade=cascade)))


@config_app.command("show")
def config_show() -> None:
    _write_json(_invoke(lambda: resolve_config().public_dict()))


def _with_client(operation: Callable[[Client], T]) -> T:
    with Client() as client:
        return operation(client)


def _invoke(operation: Callable[[], T]) -> T:
    try:
        return operation()
    except LabtaskerError as error:
        _write_json(error.as_envelope(), error=True)
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


def _write_json(value: object, *, error: bool = False) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list) and all(isinstance(item, BaseModel) for item in value):
        value = [item.model_dump(mode="json") for item in value]
    typer.echo(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        err=error,
        nl=False,
    )
