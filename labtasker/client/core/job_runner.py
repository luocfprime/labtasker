import json
import os
import sys
import time
import traceback
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union

from starlette.status import HTTP_401_UNAUTHORIZED

import labtasker
from labtasker.api_models import TaskUpdateRequest
from labtasker.client.core.api import (
    create_worker,
    delete_worker,
    fetch_task,
    get_queue,
    report_task_status,
    update_tasks,
)
from labtasker.client.core.cli_utils import Choice, make_a_choice
from labtasker.client.core.config import get_client_config
from labtasker.client.core.context import (
    current_task_id,
    current_worker_id,
    set_current_worker_id,
    set_task_info,
    task_info,
)
from labtasker.client.core.exceptions import (
    LabtaskerHTTPStatusError,
    LabtaskerRuntimeError,
    LabtaskerValueError,
    WorkerSuspended,
    _LabtaskerJobFailed,
    _LabtaskerLoopExit,
)
from labtasker.client.core.heartbeat import end_heartbeat, start_heartbeat
from labtasker.client.core.logging import log_to_file, logger, stderr_console
from labtasker.client.core.paths import get_labtasker_log_dir, set_labtasker_log_dir
from labtasker.client.core.utils import transpile_query_safe
from labtasker.utils import parse_time_interval

__all__ = [
    "loop_run",
    "finish",
    "set_loop_internal_error_handler",
    "set_prompt_on_task_failure",
]

_prompt_on_task_failure: bool = True


def _default_loop_internal_error_handler(e: Exception, failure_count: int):
    if failure_count > 10:  # TODO: hard coded
        logger.error(
            f"Internal error occurred {failure_count} times. Quitting the loop..."
        )
        raise e

    time.sleep(
        min(
            60.0,  # max backoff time
            2 ** (failure_count - 1),  # exponential backoff
        )
    )


_loop_internal_failure_count = 0
_loop_internal_error_handler: Callable[[Exception, int], None] = (
    _default_loop_internal_error_handler
)


def set_loop_internal_error_handler(handler: Callable[[Exception, int], None]):
    global _loop_internal_error_handler
    _loop_internal_error_handler = handler


def set_prompt_on_task_failure(enabled: bool):
    """
    Enable/disable interactive prompts when task failures occur.

    When enabled, users will be prompted to choose recovery actions (e.g.
    report as 'failed', which is default, or reset task status as if
    the failure never occurred) after task failures.
    """
    global _prompt_on_task_failure
    _prompt_on_task_failure = enabled


def dump_status(status: str):
    with open(get_labtasker_log_dir() / "status.json", "w") as f:
        json.dump(
            {
                "status": status,
            },
            f,  # type: ignore
            indent=4,
        )


def dump_task_info():
    with open(get_labtasker_log_dir() / "task_info.json", "w") as f:
        f.write(task_info().model_dump_json(indent=4))


def loop_run(
    required_fields: List[str],
    extra_filter: Optional[Union[str, Dict[str, Any]]] = None,
    cmd: Optional[Union[str, List[str]]] = None,
    worker_id: Optional[str] = None,
    create_worker_kwargs: Optional[Dict[str, Any]] = None,
    eta_max: Optional[str] = None,
    heartbeat_timeout: Optional[float] = None,
    pass_args_dict: bool = False,
):
    """Run the wrapped job function in loop.

    Args:
        required_fields: Fields required for task execution in a dot-separated manner. E.g. ["arg1.arg11", "arg2.arg22"]
        extra_filter: Additional filtering criteria for tasks
        cmd: Command line arguments that runs current process. Default to sys.argv
        worker_id: Specific worker ID to use
        create_worker_kwargs: Arguments for default worker creation
        eta_max: Maximum ETA for task execution.
        heartbeat_timeout: Heartbeat timeout in seconds. Default to 3 times the send interval.
        pass_args_dict: If True, passes task_info().args as first argument
    """
    if not isinstance(required_fields, list):
        raise LabtaskerValueError(
            "Invalid required_fields. Required fields must be a list of str keys."
        )

    if heartbeat_timeout is None:
        heartbeat_timeout = get_client_config().task.heartbeat_interval * 3

    if eta_max is not None:
        try:
            parse_time_interval(eta_max)
        except ValueError:
            raise LabtaskerValueError(
                f"Invalid eta_max {eta_max}. ETA max must be a valid duration string (e.g. '1h', '1h30m', '50s')"
            )

    if isinstance(extra_filter, str):  # transpile to mongodb query
        extra_filter = transpile_query_safe(query_str=extra_filter)

    # Check connection and authentication
    try:
        get_queue()
    except LabtaskerHTTPStatusError as e:
        if e.response.status_code == HTTP_401_UNAUTHORIZED:
            msg = (
                f"Either invalid credentials or queue not created. "
                f"Please check your configuration. Detail: {e}"
            )
            stderr_console.print(f"[bold red]Error:[/bold red] {msg}")
            logger.critical(msg)
        raise e

    # Create worker if not exists
    auto_create_worker = False

    if current_worker_id() is None:
        auto_create_worker = worker_id is None
        worker_id = worker_id or create_worker(**(create_worker_kwargs or {}))
        set_current_worker_id(worker_id)

    if cmd is None:
        cmd = sys.argv

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            """Run the task in loop.
            1. Call fetch_task
            2. Setup
            3. Run task
            4. Submit result (finish).
            """
            global _loop_internal_failure_count
            # Run task in a loop
            while True:
                try:
                    # Fetch task
                    resp = fetch_task(
                        worker_id=current_worker_id(),
                        eta_max=eta_max,
                        heartbeat_timeout=heartbeat_timeout,
                        start_heartbeat=True,
                        required_fields=required_fields,
                        extra_filter=extra_filter,
                        cmd=cmd,
                    )
                    if not resp.found:  # task run complete
                        logger.info(
                            f"Tasks with required fields {required_fields} and extra filter {extra_filter} are all done."
                        )
                        break

                    task = resp.task

                    logger.info(
                        f"Prepared to run task {task.task_id} with args {task.args}."
                    )

                    # Set task info
                    set_task_info(task)

                    # Setup
                    set_labtasker_log_dir(
                        task_id=task.task_id,
                        task_name=task.task_name,
                        set_env=True,
                        overwrite=True,
                    )

                    # Dump task_info.json
                    dump_task_info()

                    with log_to_file(file_path=get_labtasker_log_dir() / "run.log"):
                        start_heartbeat(task_id=current_task_id())
                        success_flag = False
                        try:
                            func_args = (task.args, *args) if pass_args_dict else args
                            func(*func_args, **kwargs)
                            success_flag = True
                        except (
                            _LabtaskerJobFailed,
                            KeyboardInterrupt,
                            BaseException,
                        ) as e:
                            # Task failure handling logic
                            # 1. Log the exception
                            # 2. Ask the user to decide what to do (only for 10s if enabled)
                            #    A. Report: Report task as failed, with number of retries decreasing.
                            #    B. Ignore: Reset task to back to PENDING with retries count set to 0, as if this crashed run never happened

                            # 1. log exception
                            if isinstance(e, KeyboardInterrupt):
                                logger.warning("KeyboardInterrupt detected")
                            else:
                                logger.error(f"Task {current_task_id()} failed")
                                if not isinstance(e, _LabtaskerJobFailed):
                                    stderr_console.print_exception(
                                        # hide traceback from internals
                                        suppress=[labtasker]
                                    )

                            # 2. ask the user
                            _next_action = "report"  # one of ["report", "ignore"]

                            if _prompt_on_task_failure:
                                # ask the user (wait for 10 seconds) to decide what to do
                                choices = [
                                    Choice(
                                        "(default) Report: Report task as failed, with number of retries decreasing.",
                                        data="report",
                                    ),
                                    Choice(
                                        "(ctrl+c) Ignore: Reset task to back to PENDING with retries count set to 0, as if this crashed run never happened.",
                                        data="ignore",
                                    ),
                                ]
                                choice = make_a_choice(
                                    question="Task interrupted or failed with the above info. You have 10 seconds to make a choice:",
                                    options=choices,
                                    # if timed out while waiting for user input, we assume the user is not present and report this crash by default
                                    default=choices[0],
                                    # if user pressed Ctrl+C, we assume the user wants to exit without reporting
                                    keyboard_interrupt_default=choices[1],
                                )

                                _next_action = choice.data

                            if _next_action == "ignore":
                                resp = update_tasks(
                                    task_updates=[
                                        TaskUpdateRequest(
                                            task_id=current_task_id(),  # noqa
                                            status="pending",  # running -> pending
                                            retries=0,
                                        )
                                    ]
                                )
                                if not resp.found:
                                    logger.error(
                                        f"Failed to reset task {current_task_id()} to PENDING."
                                    )
                                logger.info(
                                    f"Task {current_task_id()} reset to PENDING by user request."
                                )
                            else:  # report failure
                                finish(
                                    status="failed",
                                    summary={
                                        "labtasker_exception": {
                                            "type": type(e).__name__,
                                            "message": str(e),
                                            "traceback": traceback.format_exc(),
                                        }
                                    },
                                )
                                logger.info(
                                    f"Task {current_task_id()} crash incident reported."
                                )

                            if isinstance(e, KeyboardInterrupt):
                                break

                            _should_continue = True  # should the loop continue after exception has occurred and handled
                            if _prompt_on_task_failure:
                                # ask the user (wait for 10 seconds) to decide what to do
                                choices = [
                                    Choice(
                                        "(default) Continue: Continue processing other tasks in the queue.",
                                        data=True,
                                    ),
                                    Choice(
                                        "(ctrl+c) Exit: Stop the task loop and exit the program.",
                                        data=False,
                                    ),
                                ]
                                choice = make_a_choice(
                                    question="Do you want to continue processing other tasks or exit the program? (10 seconds to decide):",
                                    options=choices,
                                    # if timed out while waiting for user input, we assume the user is not present and continue by default
                                    default=choices[0],
                                    # if user pressed Ctrl+C, we assume the user wants to exit without reporting
                                    keyboard_interrupt_default=choices[1],
                                )

                                _should_continue = choice.data

                                if not _should_continue:
                                    raise _LabtaskerLoopExit()
                        finally:
                            if success_flag:
                                # Default finish. Can be overridden by the user if called somewhere deep in the wrapped func().
                                finish(status="success")
                            end_heartbeat()
                except _LabtaskerLoopExit:
                    # clean up the worker
                    if auto_create_worker:  # worker is managed automatically
                        delete_worker(worker_id=current_worker_id())

                    logger.info("Exiting task loop.")
                    break
                except WorkerSuspended:
                    logger.error("Worker suspended.")
                    break
                except Exception as e:
                    logger.exception("Error in task loop.")
                    _loop_internal_failure_count += 1
                    _loop_internal_error_handler(e, _loop_internal_failure_count)

        return wrapper

    return decorator


def finish(
    status: str,
    summary: Optional[Dict[str, Any]] = None,
    skip_if_no_labtasker: bool = True,
):
    """
    Called when a task is finished. It writes status and summary to log dir, and reports to server.
    Args:
        status:
        summary:
        skip_if_no_labtasker: If current job is not run by labtasker loop, skip the report. Otherwise, raise an error.

    Returns:

    """
    assert status in [
        "success",
        "failed",
    ], f"Invalid status {status}, should be one of ['success', 'failed']"

    if os.environ.get("LABTASKER_TASK_ID", None) is None:
        if skip_if_no_labtasker:
            return
        else:
            raise LabtaskerRuntimeError(
                "Current job is not run by labtasker loop. "
                "You can either use @labtasker.loop() decorator or labtasker loop cli to run job."
            )

    summary_file_path = get_labtasker_log_dir() / "summary.json"
    if summary_file_path.exists():
        # Skip if summary.json exists. Might be already called from subprocess.
        return

    # Write summary and status locally
    fd = os.open(summary_file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w") as f:
        json.dump(
            summary if summary else {},
            f,  # type: ignore
            indent=4,
        )

    dump_status(status=status)

    # Report task status to server
    report_task_status(
        task_id=current_task_id(),
        status=status,
        summary=summary,
        worker_id=current_worker_id(),
    )
