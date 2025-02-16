import json
import os
import traceback
from functools import wraps
from typing import Any, Dict, List, Optional, Union

from labtasker.client.core.api import (
    create_worker,
    fetch_task,
    report_task_status,
    report_worker_status,
)
from labtasker.client.core.config import get_client_config
from labtasker.client.core.context import (
    current_task_id,
    current_worker_id,
    set_current_worker_id,
    set_task_info,
)
from labtasker.client.core.heartbeat import end_heartbeat, start_heartbeat
from labtasker.client.core.logging import log_to_file, logger
from labtasker.client.core.paths import get_labtasker_log_dir, set_labtasker_log_dir
from labtasker.utils import keys_to_query_dict

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


def loop(
    required_fields: Union[Dict[str, Any], List[str]] = None,
    extra_filter: Optional[Dict[str, Any]] = None,
    worker_id: Optional[str] = None,
    create_worker_kwargs: Optional[Dict[str, Any]] = None,
    eta_max: Optional[str] = None,
    heartbeat_timeout: Optional[int] = None,
    pass_args_dict: bool = False,
):
    """Run the wrapped job function in loop.

    Args:
        required_fields: Fields required for task execution
        extra_filter: Additional filtering criteria for tasks
        worker_id: Specific worker ID to use
        create_worker_kwargs: Arguments for default worker creation
        eta_max: Maximum ETA for task execution.
        heartbeat_timeout: Heartbeat timeout in seconds. Default to 3 times the send interval.
        pass_args_dict: If True, passes task_info().args as first argument
    """
    if isinstance(required_fields, list):
        required_fields = keys_to_query_dict(required_fields)

    if heartbeat_timeout is None:
        heartbeat_timeout = get_client_config().heartbeat_interval * 3

    # Create worker if not exists
    if current_worker_id() is None:
        new_worker_id = worker_id or create_worker(**(create_worker_kwargs or {}))
        set_current_worker_id(new_worker_id)

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

                    # Set task info
                    set_task_info(resp.task)

                    # Setup
                    set_labtasker_log_dir(
                        task_id=current_task_id(), set_env=True, overwrite=True
                    )

                    with log_to_file(file_path=get_labtasker_log_dir() / "run.log"):
                        start_heartbeat(task_id=current_task_id())
                        try:
                            func_args = (
                                (resp.task.args, *args) if pass_args_dict else args
                            )
                            func(*func_args, **kwargs)

                            # Default finish. Can be overridden by the user if called somewhere deep in the wrapped func().
                            finish(status="success", summary={})
                        except BaseException as e:
                            logger.exception(f"Task {current_task_id()} failed")
                            finish(
                                status="error",
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

                except Exception:
                    logger.exception("Error in task loop.")

        return wrapper

    return decorator


def finish(status: str, summary: Optional[Dict[str, Any]] = None):
    """
    Called when a task is finished. It writes status and summary to log dir, and reports to server.
    Args:
        status:
        summary:

    Returns:

    """
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

    # Report worker status to server if failed
    if current_worker_id() is not None and status == "failed":
        report_worker_status(
            worker_id=current_worker_id(),
            status="failed",
        )
