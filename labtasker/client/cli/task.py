"""
Task related CRUD operations.
"""

import io
import tempfile
from functools import partial
from typing import Any, Dict, List, Optional, Set

import click
import rich
import ruamel.yaml
import typer
import yaml
from pydantic import ValidationError
from rich.syntax import Syntax
from starlette.status import HTTP_404_NOT_FOUND

from labtasker.api_models import Task, TaskUpdateRequest
from labtasker.client.core.api import (
    delete_task,
    get_queue,
    ls_tasks,
    report_task_status,
    submit_task,
    update_tasks,
)
from labtasker.client.core.cli_utils import (
    LsFmtChoices,
    cli_utils_decorator,
    ls_format_iter,
    pager_iterator,
    parse_metadata,
)
from labtasker.client.core.exceptions import LabtaskerHTTPStatusError
from labtasker.client.core.logging import stderr_console, stdout_console

app = typer.Typer()


def commented_seq_from_dict_list(
    entries: List[Dict[str, Any]]
) -> ruamel.yaml.CommentedSeq:
    return ruamel.yaml.CommentedSeq([ruamel.yaml.CommentedMap(e) for e in entries])


def add_eol_comment(d: ruamel.yaml.CommentedMap, fields: List[str], comment: str):
    """Add end of line comment at end of fields (in place)"""
    for key in d.keys():
        if key in fields:
            d.yaml_add_eol_comment(comment, key=key, column=50)


def dump_commented_seq(commented_seq, f):
    y = ruamel.yaml.YAML()
    y.indent(mapping=2, sequence=2, offset=0)
    y.dump(commented_seq, f)


def edit_and_reload(f, editor: str):
    click.edit(filename=f.name, editor=editor)
    f.seek(0)
    data = yaml.safe_load(f)
    return data


def diff(
    prev: List[Dict[str, Any]],
    modified: List[Dict[str, Any]],
    readonly_fields: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """

    Args:
        prev:
        modified:
        readonly_fields:

    Returns: dict storing modified key values

    """
    readonly_fields = readonly_fields or []

    updates = []
    for i, new_entry in enumerate(modified):
        u = dict()
        for k, v in new_entry.items():
            if k in readonly_fields:
                # if changed to readonly field, show a warning
                if v != prev[i][k]:
                    stderr_console.print(
                        f"[bold orange1]Warning:[/bold orange1] Field '{k}' is readonly. You are not supposed to modify it. Your modification to this field will be ignored."
                    )
                    # the modified field will be ignored by the server
                continue
            elif v != prev[i][k]:  # modified
                u[k] = v
            else:  # unchanged
                continue

        updates.append(u)

    return updates


@app.command()
@cli_utils_decorator
def submit(
    task_name: Optional[str] = typer.Option(None, help="Name of the task."),
    args: Optional[str] = typer.Option(
        None,
        help='Arguments for the task as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional metadata as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    cmd: Optional[str] = typer.Option(
        None,
        help="Command to execute for the task.",
    ),
    heartbeat_timeout: Optional[float] = typer.Option(
        60,
        help="Heartbeat timeout for the task.",
    ),
    task_timeout: Optional[int] = typer.Option(
        None,
        help="Task execution timeout.",
    ),
    max_retries: Optional[int] = typer.Option(
        3,
        help="Maximum number of retries for the task.",
    ),
    priority: Optional[int] = typer.Option(
        1,
        help="Priority of the task.",
    ),
):
    """
    Submit a new task to the queue.
    """
    args_dict = parse_metadata(args) if args else {}
    metadata_dict = parse_metadata(metadata) if metadata else {}

    task_id = submit_task(
        task_name=task_name,
        args=args_dict,
        metadata=metadata_dict,
        cmd=cmd,
        heartbeat_timeout=heartbeat_timeout,
        task_timeout=task_timeout,
        max_retries=max_retries,
        priority=priority,
    )
    stdout_console.print(f"Task submitted with ID: {task_id}")


@app.command()
@cli_utils_decorator
def report(
    task_id: str = typer.Argument(..., help="ID of the task to update."),
    status: str = typer.Argument(
        ..., help="New status for the task. One of `success`, `failed`, `cancelled`."
    ),
    summary: Optional[str] = typer.Option(
        None,
        help="Summary of the task status.",
    ),
):
    """
    Report the status of a task.
    """
    try:
        summary = parse_metadata(summary)
        report_task_status(task_id=task_id, status=status, summary=summary)
    except ValidationError as e:
        raise typer.BadParameter(e)
    stdout_console.print(f"Task {task_id} status updated to {status}.")


@app.command()
@cli_utils_decorator
def ls(
    task_id: Optional[str] = typer.Option(
        None,
        help="Filter by task ID.",
    ),
    task_name: Optional[str] = typer.Option(
        None,
        help="Filter by task name.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Optional mongodb filter as a dict string (e.g., \'{"key": "value"}\').',
    ),
    pager: bool = typer.Option(
        True,
        help="Enable pagination.",
    ),
    limit: int = typer.Option(
        100,
        help="Limit the number of tasks returned.",
    ),
    offset: int = typer.Option(
        0,
        help="Initial offset for pagination.",
    ),
    fmt: LsFmtChoices = typer.Option(
        "yaml",
        help="Output format. One of `yaml`, `jsonl`.",
    ),
):
    """List tasks in the queue."""
    get_queue()  # validate auth and queue existence, prevent err swallowed by pager

    extra_filter = parse_metadata(extra_filter)
    page_iter = pager_iterator(
        fetch_function=partial(
            ls_tasks,
            task_id=task_id,
            task_name=task_name,
            extra_filter=extra_filter,
        ),
        offset=offset,
        limit=limit,
    )
    if pager:
        click.echo_via_pager(
            ls_format_iter[fmt](
                page_iter,
                use_rich=False,
            )
        )
    else:
        for item in ls_format_iter[fmt](
            page_iter,
            use_rich=True,
        ):
            stdout_console.print(item)


@app.command()
@cli_utils_decorator
def update(
    task_id: Optional[str] = typer.Option(
        None,
        help="Filter by task ID.",
    ),
    task_name: Optional[str] = typer.Option(
        None,
        help="Filter by task name.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Optional mongodb filter as a dict string (e.g., \'{"key": "value"}\').',
    ),
    update_dict: Optional[str] = typer.Option(
        None,
        "--update",
        "-u",
        help='Optional dict string for updated values of fields (e.g., \'{"task_name": "new_name"}\').',
    ),
    offset: int = typer.Option(
        0,
        help="Initial offset for pagination (In case there are too many items for update, only 1000 results starting from offset is displayed. "
        "You would need to adjust offset to apply to other items).",
    ),
    reset_pending: bool = typer.Option(
        False,
        help="Reset pending tasks to pending after updating.",
    ),
    editor: Optional[str] = typer.Option(
        None,
        help="Editor to use for interactive update.",
    ),
):
    """Update tasks settings."""
    extra_filter = parse_metadata(extra_filter)

    # readonly fields
    readonly_fields: Set[str] = (
        Task.model_fields.keys() - TaskUpdateRequest.model_fields.keys()  # type: ignore
    )
    readonly_fields.add("task_id")

    if reset_pending:
        # these fields will be overwritten internally: status: pending, retries: 0
        readonly_fields.add("status")
        readonly_fields.add("retries")

    update_dict = parse_metadata(update_dict)

    if not update_dict:  # if no update provided, enter interactive mode
        interactive = True
    else:
        interactive = False

    old_tasks = ls_tasks(
        task_id=task_id,
        task_name=task_name,
        extra_filter=extra_filter,
        limit=1000,
        offset=offset,
    ).content

    task_updates: List[TaskUpdateRequest] = []

    # Opens a system text editor to allow modification
    if interactive:
        old_tasks_primitive: List[Dict[str, Any]] = [t.model_dump() for t in old_tasks]

        commented_seq = commented_seq_from_dict_list(old_tasks_primitive)

        # format: set line break at each entry
        for i in range(len(commented_seq) - 1):
            commented_seq.yaml_set_comment_before_after_key(key=i + 1, before="\n")

        # add "do not edit" at the end of readonly_fields
        for d in commented_seq:
            add_eol_comment(
                d, fields=list(readonly_fields), comment="Read-only. DO NOT modify!"
            )

        # open an editor to allow interaction
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".yaml") as f:
            dump_commented_seq(commented_seq=commented_seq, f=f)

            while True:  # continue to edit until no syntax error
                try:
                    modified = edit_and_reload(f=f, editor=editor)
                    break  # if no error, break
                except yaml.error.YAMLError as e:
                    stderr_console.print(
                        "[bold red]Error:[/bold red] error when parsing yaml.\n"
                        f"Detail: {str(e)}"
                    )
                    typer.confirm("Continue to edit?", abort=True)

        # make sure the len match
        if len(modified) != len(old_tasks_primitive):
            stderr_console.print(
                f"[bold red]Error:[/bold red] number of entries do not match. new {len(modified)} != old {len(old_tasks_primitive)}. "
                f"Please check your modification. You should not change the order or make deletions to entries."
            )
            raise typer.Abort()

        # make sure the order match
        for i, (m, o) in enumerate(zip(modified, old_tasks_primitive)):
            if m["task_id"] != o["task_id"]:
                stderr_console.print(
                    f"[bold red]Error:[/bold red] task_id {m['task_id']} should be {o['task_id']} at {i}th entry. "
                    "You should not modify task_id or change the order of the entries."
                )
                raise typer.Abort()

        # get a list of update dict
        updates = diff(
            prev=old_tasks_primitive,
            modified=modified,
            readonly_fields=list(readonly_fields),
        )

    else:
        # populate if not using interactive mode to modify one by one
        updates = [update_dict] * len(old_tasks)

    for i, ud in enumerate(updates):  # ud: update dict list entry
        if not ud:  # filter out empty update dict
            continue
        task_updates.append(TaskUpdateRequest(_id=old_tasks[i].task_id, **ud))

    updated_tasks = update_tasks(task_updates=task_updates, reset_pending=reset_pending)

    if not typer.confirm(
        f"Total {len(updated_tasks.content)} tasks updated complete. Do you want to see the updated result?"
    ):
        raise typer.Exit()

    # display via pager ---------------------------------------------------------------
    updated_tasks_primitive = [t.model_dump() for t in updated_tasks.content]
    commented_seq = commented_seq_from_dict_list(updated_tasks_primitive)

    # format: set line break at each entry
    for i in range(len(commented_seq) - 1):
        commented_seq.yaml_set_comment_before_after_key(key=i + 1, before="\n")

    # add "modified" comment
    for d, ud in zip(commented_seq, updates):
        add_eol_comment(
            d,
            fields=list(ud.keys()),
            comment=f"Modified",
        )

    s = io.StringIO()
    y = ruamel.yaml.YAML()
    y.indent(mapping=2, sequence=2, offset=0)
    y.dump(commented_seq, s)

    yaml_str = s.getvalue()

    console = rich.console.Console()
    with console.capture() as capture:
        console.print(Syntax(yaml_str, "yaml"))
    ansi_str = capture.get()

    click.echo_via_pager(ansi_str)


@app.command()
@cli_utils_decorator
def delete(
    task_id: str = typer.Argument(..., help="ID of the task to delete."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm the operation."),
):
    """
    Delete a task.
    """
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete task '{task_id}'?",
            abort=True,
        )
    try:
        delete_task(task_id=task_id)
        stdout_console.print(f"Task {task_id} deleted.")
    except LabtaskerHTTPStatusError as e:
        if e.response.status_code == HTTP_404_NOT_FOUND:
            raise typer.BadParameter("Task not found")
        else:
            raise e
