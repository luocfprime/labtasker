import json
import os
import sys
import traceback
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from labtasker.api_models import TaskUpdateRequest
from labtasker.client.core.api import (
    create_worker,
    fetch_task,
    report_task_status,
    update_tasks,
)
from labtasker.client.core.config import get_client_config
from labtasker.client.core.context import (
    current_task_id,
    current_worker_id,
    set_current_worker_id,
    set_task_info,
    task_info,
)
from labtasker.client.core.exceptions import (
    LabtaskerRuntimeError,
    LabtaskerValueError,
    WorkerSuspended,
)
from labtasker.client.core.heartbeat import end_heartbeat, start_heartbeat
from labtasker.client.core.logging import log_to_file, logger
from labtasker.client.core.paths import get_labtasker_log_dir, set_labtasker_log_dir
from labtasker.utils import keys_to_query_dict, parse_timeout

__all__ = ["loop", "finish"]


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


def loop(
    required_fields: Union[Dict[str, Any], List[str]] = None,
    extra_filter: Optional[Dict[str, Any]] = None,
    cmd: Optional[Union[str, List[str]]] = None,
    worker_id: Optional[str] = None,
    create_worker_kwargs: Optional[Dict[str, Any]] = None,
    eta_max: Optional[str] = None,
    heartbeat_timeout: Optional[float] = None,
    pass_args_dict: bool = False,
):
    """Run the wrapped job function in loop.

    Args:
        required_fields: Fields required for task execution. Note: the dot-separated fields are default to be parsed into a nested dict structure. e.g. ["foo.bar"] will be parsed into {"foo": {"bar": None}}. The same applies for {"foo.bar": None} which will eventually be transformed into {"foo": {"bar": None}}
        extra_filter: Additional filtering criteria for tasks
        cmd: Command line arguments that runs current process. Default to sys.argv
        worker_id: Specific worker ID to use
        create_worker_kwargs: Arguments for default worker creation
        eta_max: Maximum ETA for task execution.
        heartbeat_timeout: Heartbeat timeout in seconds. Default to 3 times the send interval.
        pass_args_dict: If True, passes task_info().args as first argument
    """
    if isinstance(required_fields, list):
        required_fields = keys_to_query_dict(required_fields)

    if not isinstance(required_fields, dict):
        raise LabtaskerValueError(
            "Invalid required_fields. Required fields must be a dict or a list of str keys."
        )

    if heartbeat_timeout is None:
        heartbeat_timeout = get_client_config().task.heartbeat_interval * 3

    if eta_max is not None:
        try:
            parse_timeout(eta_max)
        except ValueError:
            raise LabtaskerValueError(
                f"Invalid eta_max {eta_max}. ETA max must be a valid duration string (e.g. '1h', '1h30m', '50s')"
            )

    # Create worker if not exists
    if current_worker_id() is None:
        new_worker_id = worker_id or create_worker(**(create_worker_kwargs or {}))
        set_current_worker_id(new_worker_id)

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
                    )
                    if not resp.found:  # task run complete
                        logger.info(
                            f"Tasks with required fields {required_fields} and extra filter {extra_filter} are all done."
                        )
                        break

                    # update the "cmd" field of the current task, and get the updated task info
                    task = update_tasks(
                        [TaskUpdateRequest(task_id=resp.task.task_id, cmd=cmd)],  # noqa
                        reset_pending=False,
                    ).content[0]

                    logger.info(
                        f"Prepared to run task {task.task_id} with args {task.args}."
                    )

                    # Set task info
                    set_task_info(task)

                    # Setup
                    set_labtasker_log_dir(
                        task_id=current_task_id(), set_env=True, overwrite=True
                    )

                    # Dump task_info.json
                    dump_task_info()

                    with log_to_file(file_path=get_labtasker_log_dir() / "run.log"):
                        start_heartbeat(task_id=current_task_id())
                        try:
                            func_args = (task.args, *args) if pass_args_dict else args
                            func(*func_args, **kwargs)

                            # Default finish. Can be overridden by the user if called somewhere deep in the wrapped func().
                            finish(status="success", summary={})
                        except BaseException as e:
                            logger.exception(f"Task {current_task_id()} failed")
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
                        finally:
                            end_heartbeat()
                except WorkerSuspended:
                    logger.info("Worker suspended.")
                    break
                except Exception:
                    logger.exception("Error in task loop.")

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
        summary=summary if summary else {},
    )
