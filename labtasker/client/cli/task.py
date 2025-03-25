"""Manage tasks (CRUD operations)."""

import io
import json
import os
import sys
import tempfile
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import click
import pydantic
import rich
import ruamel.yaml
import typer
import yaml
from rich.syntax import Syntax
from starlette.status import HTTP_404_NOT_FOUND
from typing_extensions import Annotated

from labtasker.api_models import Task, TaskUpdateRequest
from labtasker.client.core.api import (
    delete_task,
    get_queue,
    ls_tasks,
    submit_task,
    update_tasks,
)
from labtasker.client.core.cli_utils import (
    LsFmtChoices,
    cli_utils_decorator,
    confirm,
    ls_format_iter,
    pager_iterator,
    parse_dict,
    parse_extra_opt,
    parse_filter,
    parse_metadata,
    parse_sort,
    parse_updates,
)
from labtasker.client.core.exceptions import LabtaskerHTTPStatusError
from labtasker.client.core.logging import (
    set_verbose,
    stderr_console,
    stdout_console,
    verbose_print,
)
from labtasker.constants import Priority

app = typer.Typer()


def commented_seq_from_dict_list(
    entries: List[Dict[str, Any]],
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
            help="Task arguments in command-line format. Use -- to separate from other options. Example: -- --input-file data.csv --model xgboost",
        ),
    ] = None,
    task_name: Optional[str] = typer.Option(
        None,
        "--task-name",
        "--name",
        help="Descriptive name for the task to help with identification.",
    ),
    option_args: Optional[str] = typer.Option(
        None,
        "--args",
        help='Alternative way to specify task arguments as a Python dictionary (e.g., \'{"input_file": "data.csv", "model": "xgboost"}\').',
    ),
    metadata: Optional[str] = typer.Option(
        None,
        help='Additional task metadata as a Python dictionary (e.g., \'{"tags": ["experiment", ML"]]}\').',
    ),
    cmd: Optional[str] = typer.Option(
        None,
        help="Command string to execute this task (rarely needed, as commands are typically defined in the worker).",
    ),
    heartbeat_timeout: Optional[float] = typer.Option(
        60,
        help="Time in seconds before a task is considered failed if no heartbeat is received.",
    ),
    task_timeout: Optional[int] = typer.Option(
        None,
        help="Maximum allowed execution time for the task in seconds.",
    ),
    max_retries: Optional[int] = typer.Option(
        3,
        help="Number of retry attempts if the task fails.",
    ),
    priority: Optional[int] = typer.Option(
        Priority.MEDIUM,
        help="Task priority (higher numbers = higher priority). Default is medium priority.",
    ),
):
    """
    Submit a new task to the queue for processing.

    Tasks contain arguments that will be passed to workers for execution.
    You can specify arguments either as command-line style parameters or as a JSON dictionary.

    Examples:
        labtasker task submit --name "process-batch-5" -- --input data.csv --output results/
        labtasker task submit --name "train-model" --args '{"dataset": "mnist", "epochs": 10}'
    """
    if args and option_args:
        raise typer.BadParameter(
            "You can only specify one of the [ARGS] or `--args`. "
            "That is, via positional argument or as an option."
        )

    args_dict = parse_dict(option_args) if option_args else parse_extra_opt(args or [])
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
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by task status. One of `pending`, `running`, `success`, `failed`, `cancelled`.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Optional mongodb filter as a dict string (e.g., \'{"$and": [{"metadata.tag": {"$in": ["a", "b"]}}, {"priority": 10}]}\'). '
        'Or a Python expression (e.g. \'metadata.tag in ["a", "b"] and priority == 10\')',
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        "-q",
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
    sort: Optional[List[str]] = typer.Option(
        None,
        "--sort",
        "-S",
        help="Sort by field and direction. "
        "e.g. `-S 'created_at:desc' -S 'last_modified:asc'`",
    ),
    fmt: LsFmtChoices = typer.Option(
        "yaml",
        help="Output format. One of `yaml`, `jsonl`.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output.",
        callback=set_verbose,
        is_eager=True,
    ),
):
    """
    List and filter tasks in the queue.

    This command displays tasks matching the specified filters, with support for
    pagination, sorting, and different output formats.

    Examples:
        labtasker task ls                                # List all tasks
        labtasker task ls --status pending               # List only pending tasks
        labtasker task ls --name "training-job"          # Filter by task name
        labtasker task ls -f 'priority > 5'              # Filter by priority
        labtasker task ls -S 'created_at:desc'           # Sort by creation time
    """
    if quiet:
        if verbose:
            raise typer.BadParameter(
                "You can only specify one of the options --verbose and --quiet."
            )
        pager = False

    if not sort:
        parsed_sort = [
            ("priority", -1),
            ("last_modified", 1),
            ("created_at", 1),
        ]
    else:
        parsed_sort = parse_sort(sort)

    get_queue()  # validate auth and queue existence, prevent err swallowed by pager

    extra_filter = parse_filter(extra_filter)
    verbose_print(f"Parsed filter: {json.dumps(extra_filter, indent=4)}")
    page_iter = pager_iterator(
        fetch_function=partial(
            ls_tasks,
            task_id=task_id,
            task_name=task_name,
            status=status,
            extra_filter=extra_filter,
            sort=parsed_sort,
        ),
        offset=offset,
        limit=limit,
    )

    if quiet:
        for item in page_iter:
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
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by task status. One of `pending`, `running`, `success`, `failed`, `cancelled`.",
    ),
    extra_filter: Optional[str] = typer.Option(
        None,
        "--extra-filter",
        "-f",
        help='Optional mongodb filter as a dict string (e.g., \'{"$and": [{"metadata.tag": {"$in": ["a", "b"]}}, {"priority": 10}]}\'). '
        'Or a Python expression (e.g. \'metadata.tag in ["a", "b"] and priority == 10\')',
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
        "--quiet",
        "-q",
        help="Disable interactive mode and confirmations. Set this to true if you are using this in a bash script.",
    ),
    editor: Optional[str] = typer.Option(
        None,
        help="Editor to use for modifying task data incase you didn't specify --update.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose output.",
        callback=set_verbose,
        is_eager=True,
    ),
):
    """
    Update existing tasks.

    This command allows you to modify task properties like arguments, metadata,
    priority, and other settings. You can update multiple tasks at once by using
    filters, and either specify updates directly or use an interactive editor.

    Examples:
        labtasker task update --id "task-123" -- priority=10
        labtasker task update --status pending -- metadata.tag=important
        labtasker task update --name "training" --editor vim  # Open in editor
    """
    if updates and option_updates:
        raise typer.BadParameter(
            "You can only specify one of the positional argument [UPDATES] or option --update."
        )

    if verbose and quiet:
        raise typer.BadParameter(
            "You can only specify one of the options --verbose and --quiet."
        )

    updates = updates or option_updates
    extra_filter = parse_filter(extra_filter)
    verbose_print(f"Parsed filter: {json.dumps(extra_filter, indent=4)}")

    # readonly fields
    readonly_fields: Set[str] = (
        Task.model_fields.keys() - TaskUpdateRequest.model_fields.keys()  # type: ignore
    )
    readonly_fields.add("task_id")

    if reset_pending:
        readonly_fields.update({"status", "retries"})

    old_tasks = ls_tasks(
        task_id=task_id,
        task_name=task_name,
        status=status,
        extra_filter=extra_filter,
        limit=1000,
        offset=offset,
    ).content
    use_editor = not updates

    if quiet and use_editor:
        raise typer.BadParameter("You must specify --update when using --quiet.")

    if use_editor:
        task_updates = handle_editor_mode(old_tasks, readonly_fields, editor)
    else:
        task_updates = handle_non_editor_mode(old_tasks, updates, readonly_fields)

    updated_tasks = update_tasks(task_updates=task_updates, reset_pending=reset_pending)
    if confirm(
        f"Total {len(updated_tasks.content)} tasks updated. View result?",
        quiet=quiet,
        default=False,
    ):
        display_updated_tasks(updated_tasks=updated_tasks, update_dicts=task_updates)


def handle_editor_mode(old_tasks, readonly_fields, editor):
    """Handles editing tasks using a system editor and returns task updates."""
    old_tasks_primitive = [t.model_dump() for t in old_tasks]

    # Create a commented sequence once at the beginning
    commented_seq = commented_seq_from_dict_list(old_tasks_primitive)
    for i in range(len(commented_seq) - 1):
        commented_seq.yaml_set_comment_before_after_key(key=i + 1, before="\n")
    for d in commented_seq:
        add_eol_comment(
            d, fields=list(readonly_fields), comment="Read-only. DO NOT modify!"
        )

    temp_file_path = None
    try:
        fd, temp_file_path = tempfile.mkstemp(prefix="labtasker.tmp.", suffix=".yaml")
        os.close(fd)
        temp_file_path = Path(temp_file_path)

        # Write the initial state to the temp file (outside the loop)
        with open(temp_file_path, "w", encoding="utf-8") as temp_file:
            dump_commented_seq(commented_seq=commented_seq, f=temp_file)

        while True:
            try:
                # Edit the file
                click.edit(filename=str(temp_file_path), editor=editor)

                # Read the modified content
                with open(temp_file_path, "r", encoding="utf-8") as temp_file:
                    modified = yaml.safe_load(temp_file)

                # Calculate diffs and create task updates
                update_dicts = diff(
                    old_tasks_primitive, modified, readonly_fields=list(readonly_fields)
                )
                replace_fields_list = [
                    [k for k, v in ud.items() if k not in readonly_fields]
                    for ud in update_dicts
                ]

                # Try to create task updates
                task_updates = []
                validation_errors = False

                for i, (ud, replace_fields) in enumerate(
                    zip(update_dicts, replace_fields_list)
                ):
                    if not ud:
                        continue
                    try:
                        task_updates.append(
                            TaskUpdateRequest(
                                _id=old_tasks[i].task_id,
                                replace_fields=replace_fields,
                                **ud,
                            )
                        )
                    except pydantic.ValidationError as e:
                        error_messages = "; ".join(
                            [f"{err['loc'][0]}: {err['msg']}" for err in e.errors()]
                        )
                        stderr_console.print(
                            f"[bold red]Validation Error for task {old_tasks[i].task_id}:[/bold red] {error_messages}"
                        )
                        validation_errors = True

                if validation_errors:
                    if not typer.confirm("Continue to edit?", default=True):
                        raise typer.Abort()
                    # Continue the loop with the current file state
                else:
                    # No validation errors, we can break the loop
                    break

            except yaml.error.YAMLError as e:
                stderr_console.print(f"[bold red]YAML Error:[/bold red] {str(e)}")
                if not typer.confirm("Continue to edit?", default=True):
                    raise typer.Abort()
                # Continue the loop with the current file state

    finally:
        if temp_file_path and temp_file_path.exists():
            temp_file_path.unlink()

    return task_updates


def handle_non_editor_mode(old_tasks, updates, readonly_fields):
    """Handles update tasks without an editor and returns task updates."""
    replace_fields, update_dict = parse_updates(
        updates, top_level_fields=list(TaskUpdateRequest.model_fields.keys())  # type: ignore
    )

    # Check for readonly field modification
    for k in list(update_dict.keys()):
        if k in readonly_fields:
            stderr_console.print(
                f"[bold orange1]Warning:[/bold orange1] Field '{k}' is readonly. "
                f"You are not supposed to modify it. Your modification to this field will be ignored."
            )
            # readonly fields modifications will be discarded by the server

    task_updates = []
    for i, task in enumerate(old_tasks):
        task_updates.append(
            TaskUpdateRequest(
                _id=task.task_id, replace_fields=replace_fields, **update_dict
            )
        )

    return task_updates


def display_updated_tasks(updated_tasks, update_dicts):
    """Displays updated tasks in a formatted YAML output."""
    updated_tasks_primitive = [t.model_dump() for t in updated_tasks.content]
    commented_seq = commented_seq_from_dict_list(updated_tasks_primitive)

    # Format: set line break at each entry
    for i in range(len(commented_seq) - 1):
        commented_seq.yaml_set_comment_before_after_key(key=i + 1, before="\n")

    # Add "Modified" comment to the fields that were actually modified
    if update_dicts:
        # Extract the modified fields from each task update
        for i, task_update in enumerate(update_dicts):
            # Skip if we don't have a corresponding task in the commented sequence
            if i >= len(commented_seq):
                continue

            # Convert TaskUpdateRequest to dict and extract modified fields
            update_dict = task_update.model_dump()

            # Get replace_fields if available, otherwise default to all non-system fields
            modified_fields = (
                task_update.replace_fields
                if hasattr(task_update, "replace_fields")
                else []
            )

            # If replace_fields is empty or not available, try to infer from the update
            if not modified_fields:
                modified_fields = [
                    k for k in update_dict.keys() if k not in ("_id", "replace_fields")
                ]

            # Add comment for each modified field
            if modified_fields:
                add_eol_comment(
                    commented_seq[i],
                    fields=modified_fields,
                    comment="Modified",
                )

    # Convert to string
    s = io.StringIO()
    y = ruamel.yaml.YAML()
    y.indent(mapping=2, sequence=2, offset=0)
    y.dump(commented_seq, s)

    # Display in pager with syntax highlighting
    console = rich.console.Console()
    with console.capture() as capture:
        console.print(Syntax(s.getvalue(), "yaml"))
    click.echo_via_pager(capture.get())


@app.command()
@cli_utils_decorator
def delete(
    task_ids: List[str] = typer.Argument(
        ... if sys.stdin.isatty() else None,
        help="IDs of the task to delete.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """
    Delete a task from the queue.

    This command permanently removes a task from the queue. By default, it will
    ask for confirmation before deletion.

    Example:
        labtasker task delete task-123
        labtasker task delete task-123 --yes  # Skip confirmation
    """
    if task_ids is None:  # read from stdin to support piping
        task_ids = [line.strip() for line in sys.stdin.readlines() if line.strip()]
    if not yes:
        typer.confirm(
            f"Are you sure you want to delete tasks '{task_ids}'?",
            abort=True,
        )
    try:
        for task_id in task_ids:
            delete_task(task_id=task_id)
            stdout_console.print(f"Task {task_id} deleted.")
    except LabtaskerHTTPStatusError as e:
        if e.response.status_code == HTTP_404_NOT_FOUND:
            raise typer.BadParameter("Task not found")
        else:
            raise e
