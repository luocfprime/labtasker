from typing import Any, Dict, List, Optional, Union

from labtasker.client.core.api import *  # noqa: F403
from labtasker.client.core.context import (
    current_task_id,
    current_worker_id,
    is_enabled,
    task_info,
)
from labtasker.client.core.events import EventListener, connect_events
from labtasker.client.core.exceptions import LabtaskerTypeError, LabtaskerValueError
from labtasker.client.core.job_runner import (
    finish,
    loop_run,
    set_loop_internal_error_handler,
    set_prompt_on_task_failure,
)
from labtasker.client.core.paths import get_labtasker_log_dir
from labtasker.client.core.resolver import (
    Required,
    get_params_from_function,
    get_required_fields,
    resolve_args_partial,
)
from labtasker.client.core.utils import run_with_pty, run_with_subprocess
from labtasker.utils import validate_required_fields

__all__ = [
    # python job runner api
    "loop",
    "finish",
    "set_loop_internal_error_handler",
    "set_prompt_on_task_failure",
    "Required",
    # context api
    "task_info",
    "current_task_id",
    "current_worker_id",
    "is_enabled",
    "get_labtasker_log_dir",
    # event api
    "connect_events",
    "EventListener",
    # http api (you should be careful with these unless you know what you are doing)
    "get_httpx_client",
    "close_httpx_client",
    "health_check",
    "create_queue",
    "get_queue",
    "delete_queue",
    "submit_task",
    "fetch_task",
    "report_task_status",
    "refresh_task_heartbeat",
    "create_worker",
    "ls_workers",
    "report_worker_status",
    "ls_tasks",
    "update_tasks",
    "delete_task",
    "update_queue",
    "delete_worker",
    # utilities
    "run_with_pty",
    "run_with_subprocess",
]

assert len(set(__all__)) == len(__all__), "Duplicated symbols in __all__"


def loop(
    required_fields: Optional[List[str]] = None,
    extra_filter: Optional[Union[str, Dict[str, Any]]] = None,
    cmd: Optional[Union[str, List[str]]] = None,
    worker_id: Optional[str] = None,
    create_worker_kwargs: Optional[Dict[str, Any]] = None,
    eta_max: Optional[str] = None,
    heartbeat_timeout: Optional[float] = None,
    pass_args_dict: bool = False,
):
    """Continuously run the wrapped job function with fetched task arguments until no tasks available.

    Args:
        required_fields: Fields (or extra fields other than specified using Required(...)) required for task execution in a dot-separated manner. E.g. ["arg1.arg11", "arg2.arg22"]
        extra_filter: Additional filtering criteria for tasks. Dict in MongoDB syntax or string in Python syntax is allowed.
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
