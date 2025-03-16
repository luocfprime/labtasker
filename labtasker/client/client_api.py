from typing import Any, Dict, List, Optional, Union

from labtasker.client.core.api import *  # noqa: F403
from labtasker.client.core.context import current_task_id, current_worker_id, task_info
from labtasker.client.core.events import EventListener, connect_events
from labtasker.client.core.exceptions import LabtaskerTypeError, LabtaskerValueError
from labtasker.client.core.job_runner import (
    finish,
    loop_run,
    set_loop_internal_error_handler,
)
from labtasker.client.core.resolver import (
    Required,
    get_params_from_function,
    get_required_fields,
    resolve_args_partial,
)
from labtasker.utils import validate_required_fields

__all__ = [
    # python job runner api
    "loop",
    "finish",
    "set_loop_internal_error_handler",
    "Required",
    # context api
    "task_info",
    "current_task_id",
    "current_worker_id",
    # event api
    "connect_events",
    "EventListener",
    # http api (you should be careful with these unless you know what you are doing)
    "close_httpx_client",
    "health_check",
    "submit_task",
    "delete_worker",
    "create_queue",
    "create_worker",
    "delete_queue",
    "delete_task",
    "delete_worker",
    "fetch_task",
    "get_queue",
    "health_check",
    "ls_tasks",
    "ls_workers",
    "refresh_task_heartbeat",
    "report_task_status",
]


def loop(
    required_fields: Optional[List[str]] = None,
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
        required_fields: Fields (or extra fields other than specified using Required(...)) required for task execution in a dot-separated manner. E.g. ["arg1.arg11", "arg2.arg22"]
        extra_filter: Additional filtering criteria for tasks
        cmd: Command line arguments that runs current process. Default to sys.argv
        worker_id: Specific worker ID to use
        create_worker_kwargs: Arguments for default worker creation
        eta_max: Maximum ETA for task execution.
        heartbeat_timeout: Heartbeat timeout in seconds. Default to 3 times the send interval.
        pass_args_dict: If True, passes task_info().args as first argument

    Returns:
        The decorated function

    """
    try:
        if required_fields is not None:
            validate_required_fields(required_fields)
    except ValueError as e:
        raise LabtaskerValueError(str(e)) from e
    except TypeError as e:
        raise LabtaskerTypeError(str(e)) from e

    def decorator(func):
        """
        Steps:
            1. Try get required fields from type annotations.
            2. Wrap the job function with an args resolver wrapper
            3. Wrap the resolver-wrapped job function with loop_run
            4. Return the wrapped function

        Args:
            func:

        Returns:

        """
        param_metas = get_params_from_function(func)

        # if required_fields is provided, merge them with the ones specified in param_metas
        all_required_fields = get_required_fields(
            param_metas=param_metas, extra_required_fields=required_fields
        )

        # wrap the job function with args resolver
        # that is, fill in the positional and keyword arguments for the required fields, type cast them
        # into custom types (e.g. dataclasses) if the type_caster is provided
        func = resolve_args_partial(
            func, param_metas=param_metas, pass_args_dict=pass_args_dict
        )

        # return the decorated function
        return loop_run(
            required_fields=all_required_fields,
            extra_filter=extra_filter,
            cmd=cmd,
            worker_id=worker_id,
            create_worker_kwargs=create_worker_kwargs,
            eta_max=eta_max,
            heartbeat_timeout=heartbeat_timeout,
            pass_args_dict=True,
        )(func)

    return decorator
