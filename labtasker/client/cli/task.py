"""
Task related CRUD operations.
"""

import io
import os
import tempfile
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import click
import rich
import ruamel.yaml
import typer
import yaml
from pydantic import ValidationError
from rich.syntax import Syntax
from starlette.status import HTTP_404_NOT_FOUND
from typing_extensions import Annotated

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
    confirm,
    ls_format_iter,
    pager_iterator,
    parse_extra_opt,
    parse_metadata,
    parse_updates,
)
from labtasker.client.core.exceptions import LabtaskerHTTPStatusError
from labtasker.client.core.logging import stderr_console, stdout_console
from labtasker.constants import Priority

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


# def edit_and_reload(f, editor: str):
#     """Edit a file and reload its contents.

#     Args:
#         f: File object to edit
#         editor: Editor to use

#     Returns:
#         The loaded YAML data from the edited file
#     """
#     # Create a temporary file
#     temp_file_path = None
#     try:
#         # Create a temporary file
#         fd, temp_file_path = tempfile.mkstemp(prefix="labtasker.tmp.", suffix=".yaml")
#         os.close(fd)  # Close the file descriptor to avoid locking issues
#         temp_file_path = Path(temp_file_path)

#         # Copy content from the original file to the temporary file
#         f.seek(0)
#         with open(temp_file_path, "wb") as temp_file:
#             temp_file.write(f.read())

#         # Open the file in the editor
#         click.edit(filename=str(temp_file_path), editor=editor)

#         # Read the edited content
#         with open(temp_file_path, "r", encoding="utf-8") as temp_file:
#             data = yaml.safe_load(temp_file)

#         return data
#     finally:
#         # Cleanup: Delete the temporary file
#         if temp_file_path and Path(temp_file_path).exists():
#             Path(temp_file_path).unlink()


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
                        f"[bold orange1]Warning:[/bold orange1] Field '{k}' is readonly. "
                        f"You are not supposed to modify it. Your modification to this field will be ignored."
                    )
                    # the modified field will be ignored by the server
                continue
            elif v != prev[i][k]:  # modified
                u[k] = v
            else:  # unchanged
                continue

        updates.append(u)

    return updates


@app.callback(invoke_without_command=True)
def callback(
    ctx: typer.Context,
):
    if not ctx.invoked_subcommand:
        stdout_console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
@cli_utils_decorator
def submit(
    args: Annotated[
        List[str],
        typer.Argument(
            ...,
            help="Arguments for the task as positional argument. "
            "e.g. `labtasker task submit --task-name 'my-task' -- --arg1 foo --arg2 bar`",
        ),
    ] = None,
    task_name: Optional[str] = typer.Option(
        None,
        "--task-name",
        "--name",
        help="Name of the task.",
    ),
    option_args: Optional[str] = typer.Option(
        None,
        "--args",
        help="Arguments for the task as a python dict string in CLI option "
        '(e.g., --args \'{"key": "value"}\').',
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help='Optional metadata as a python dict string (e.g., \'{"key": "value"}\').',
    ),
    cmd: Optional[str] = typer.Option(
        None,
        help="The command intended to execute the task. "
        "It is better to use task arguments instead of cmd, "
        "as cmd is rarely used in the task dispatch workflow "
        "and may be overwritten during task loop execution.",
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
        Priority.MEDIUM,
        help="Priority of the task. The larger the number, the higher the priority.",
    ),
):
    """
    Submit a new task to the queue.
    """
    if args and option_args:
        raise typer.BadParameter(
            "You can only specify one of the [ARGS] or `--args`. "
            "That is, via positional argument or as an option."
        )

    args_dict = (
        parse_metadata(option_args) if option_args else parse_extra_opt(args or [])
    )
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
        "--task-id",
        "--id",
        help="Filter by task ID.",
    ),
    task_name: Optional[str] = typer.Option(
        None,
        "--task-name",
        "--name",
        help="Filter by task name.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Optional mongodb filter as a dict string (e.g., \'{"$and": [{"metadata.tag": {"$in": ["a", "b"]}}, {"priority": 10}]}\').',
    ),
    quiet: bool = typer.Option(
        False,
        help="Only show task IDs that match the query, rather than full entry. "
        "Useful when using in bash scripts.",
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
    if quiet and pager:
        raise typer.BadParameter("--quiet and --pager cannot be used together.")

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

    if quiet:
        for item in page_iter:
            item: Task
            stdout_console.print(item.task_id)
        raise typer.Exit()  # exit directly without other printing

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
    updates: Annotated[
        List[str],
        typer.Argument(
            ...,
            help="Updated values of fields (recommended over --update option). "
            "e.g. `labtasker task update --task-name 'my-task' -- args.arg1=1.20 metadata.label=test`",
        ),
    ] = None,
    task_id: Optional[str] = typer.Option(
        None,
        "--task-id",
        "--id",
        help="Filter by task ID.",
    ),
    task_name: Optional[str] = typer.Option(
        None,
        "--task-name",
        "--name",
        help="Filter by task name.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Optional mongodb filter as a dict string (e.g., \'{"$and": [{"metadata.tag": {"$in": ["a", "b"]}}, {"priority": 10}]}\').',
    ),
    option_updates: Optional[List[str]] = typer.Option(
        None,
        "--update",
        "-u",
        help="Updated values of fields. Specify multiple options via repeating `-u`. "
        "E.g. `labtasker task update -u args.arg1=foo -u metadata.tag=test`",
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
    quiet: bool = typer.Option(
        False,
        help="Disable interactive mode and confirmations. Set this to true if you are using this in a bash script.",
    ),
    editor: Optional[str] = typer.Option(
        None,
        help="Editor to use for modifying task data incase you didn't specify --update.",
    ),
):
    """Update tasks settings."""
    if updates and option_updates:
        raise typer.BadParameter(
            "You can only specify one of the positional argument [UPDATES] or option --update."
        )

    updates = updates if updates else option_updates

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

    if not updates:  # if no update provided, enter use_editor mode
        use_editor = True
    else:
        use_editor = False

    if quiet and use_editor:
        raise typer.BadParameter("You must specify --update when using --quiet.")

    old_tasks = ls_tasks(
        task_id=task_id,
        task_name=task_name,
        extra_filter=extra_filter,
        limit=1000,
        offset=offset,
    ).content

    task_updates: List[TaskUpdateRequest] = []

    # Opens a system text editor to allow modification
    if use_editor:
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
        temp_file_path = None
        try:
            # Create a temporary file
            fd, temp_file_path = tempfile.mkstemp(
                prefix="labtasker.tmp.", suffix=".yaml"
            )
            os.close(fd)  # Close the file descriptor to avoid locking issues
            temp_file_path = Path(temp_file_path)

            # Write the content to the temporary file
            with open(temp_file_path, "w", encoding="utf-8") as temp_file:
                dump_commented_seq(commented_seq=commented_seq, f=temp_file)

            while True:  # continue to edit until no syntax error
                try:
                    # Open the file in the editor
                    click.edit(filename=str(temp_file_path), editor=editor)

                    # Read the edited content
                    with open(temp_file_path, "r", encoding="utf-8") as temp_file:
                        modified = yaml.safe_load(temp_file)
                    break  # if no error, break
                except yaml.error.YAMLError as e:
                    stderr_console.print(
                        "[bold red]Error:[/bold red] error when parsing yaml.\n"
                        f"Detail: {str(e)}"
                    )
                    if not typer.confirm("Continue to edit?", abort=True):
                        raise typer.Abort()
        finally:
            # Cleanup: Delete the temporary file
            if temp_file_path and temp_file_path.exists():
                temp_file_path.unlink()

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
        update_dicts = diff(
            prev=old_tasks_primitive,
            modified=modified,
            readonly_fields=list(readonly_fields),
        )

        # for editor mode, all modified field values are suppose to **replace** the original task field values entirely
        replace_fields_list = []
        for ud in update_dicts:
            modified_fields = [k for k, v in ud.items() if k not in readonly_fields]
            replace_fields_list.append(modified_fields)
    else:
        # parse the updates
        replace_fields, update_dict = parse_updates(
            updates=updates,
            top_level_fields=list(TaskUpdateRequest.model_fields.keys()),  # type: ignore
        )

        # populate if not using use_editor mode to modify one by one
        update_dicts = [update_dict] * len(old_tasks)
        replace_fields_list = [replace_fields] * len(old_tasks)

    for i, (ud, replace_fields) in enumerate(
        zip(update_dicts, replace_fields_list)
    ):  # ud: update dict list entry
        if not ud:  # filter out empty update dict
            continue

        task_updates.append(
            TaskUpdateRequest(
                _id=old_tasks[i].task_id, replace_fields=replace_fields, **ud
            )
        )

    updated_tasks = update_tasks(task_updates=task_updates, reset_pending=reset_pending)

    if not confirm(
        f"Total {len(updated_tasks.content)} tasks updated complete. Do you want to see the updated result?",
        quiet=quiet,
        default=False,
    ):
        raise typer.Exit()

    # display via pager ---------------------------------------------------------------
    updated_tasks_primitive = [t.model_dump() for t in updated_tasks.content]
    commented_seq = commented_seq_from_dict_list(updated_tasks_primitive)

    # format: set line break at each entry
    for i in range(len(commented_seq) - 1):
        commented_seq.yaml_set_comment_before_after_key(key=i + 1, before="\n")

    # add "modified" comment
    for d, ud in zip(commented_seq, update_dicts):
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
