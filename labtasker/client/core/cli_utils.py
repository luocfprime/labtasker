from ast import literal_eval
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, Iterable, Optional

import httpx
import pydantic
import typer
import yaml
from pydantic import BaseModel
from rich.console import Console
from rich.json import JSON
from rich.syntax import Syntax
from starlette.status import HTTP_401_UNAUTHORIZED

from labtasker.client.core.api import health_check
from labtasker.client.core.config import requires_client_config
from labtasker.client.core.logging import stderr_console
from labtasker.utils import parse_timeout


class LsFmtChoices(str, Enum):
    jsonl = "jsonl"
    yaml = "yaml"


def parse_metadata(metadata: str) -> Optional[Dict[str, Any]]:
    """
    Parse metadata string into a dictionary.
    Raise typer.BadParameter if the input is invalid.
    """
    if not metadata:
        return None
    try:
        parsed = literal_eval(metadata)
        if not isinstance(parsed, dict):
            raise ValueError("Metadata must be a dictionary.")
        return parsed
    except (ValueError, SyntaxError) as e:
        raise typer.BadParameter(f"Invalid metadata: {e}")


def eta_max_validation(value: Optional[str]):
    if value is None:
        return None
    try:
        parse_timeout(value)
    except Exception:
        raise typer.BadParameter(
            "ETA max must be a valid duration string (e.g. '1h', '1h30m', '50s')"
        )
    return value


def ls_jsonl_format_iter(
    iterator: Iterable[BaseModel], exclude_unset: bool = False, use_rich: bool = True
):
    console = Console()
    for item in iterator:
        json_str = f"{item.model_dump_json(indent=4, exclude_unset=exclude_unset)}\n"
        if use_rich:
            yield JSON(json_str)
        else:
            with console.capture() as capture:
                console.print_json(json_str)
            ansi_str = capture.get()
            yield ansi_str


def ls_yaml_format_iter(
    iterator: Iterable[BaseModel], exclude_unset: bool = False, use_rich: bool = True
):
    console = Console()
    for item in iterator:
        yaml_str = f"{yaml.dump([item.model_dump(exclude_unset=exclude_unset)], indent=2, sort_keys=False)}\n"
        syntax = Syntax(yaml_str, "yaml")
        if use_rich:
            yield syntax
        else:
            with console.capture() as capture:
                console.print(syntax)
            ansi_str = capture.get()
            yield ansi_str


def pager_iterator(
    fetch_function: Callable,
    offset: int = 0,
    limit: int = 100,
):
    """
    Iterator to fetch items in a paginated manner.

    Args:
        fetch_function: ls related API calling function
        offset: initial offset
        limit: limit per API call
    """
    while True:
        response = fetch_function(limit=limit, offset=offset)

        if (
            not response.found or not response.content
        ):  # every ls response has "found" and "content" fields
            break  # Exit if no more items are found

        for item in response.content:  # Adjust this based on the response structure
            yield item  # Yield each item

        offset += limit  # Increment offset for the next batch


def requires_server_connection(func: Optional[Callable] = None, /):
    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                status = health_check()
                assert status.status == "healthy"
            except (AssertionError, httpx.HTTPStatusError, httpx.ConnectError) as e:
                stderr_console.print(
                    "[bold red]Error:[/bold red] Server connection is not healthy. Please check your connection.\n"
                    f"Detail: {e}"
                )
                raise typer.Abort()
            return function(*args, **kwargs)

        return wrapped

    if func is None:
        return decorator

    return decorator(func)


def validation_err_to_typer_err(func: Optional[Callable] = None, /):
    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except pydantic.ValidationError as e:
                error_messages = "; ".join(
                    [f"{err['loc'][0]}: {err['msg']}" for err in e.errors()]
                )
                raise typer.BadParameter(f"{error_messages}")

        return wrapped

    if func is None:
        return decorator

    return decorator(func)


def http_401_unauthorized_to_typer_err(func: Optional[Callable] = None, /):
    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == HTTP_401_UNAUTHORIZED:
                    stderr_console.print(
                        "[bold red]Error:[/bold red] Invalid credentials. Please check your configuration."
                        f"Detail: {e}"
                    )
                    raise typer.Abort()
                else:
                    raise e

        return wrapped

    if func is None:
        return decorator

    return decorator(func)


def cli_utils_decorator(
    func: Optional[Callable] = None,
    /,
    *,
    enable_requires_client_config: bool = True,
    enable_requires_server_connection: bool = True,
    enable_validation_err_to_typer_err: bool = True,
    enable_http_401_unauthorized_to_typer_err: bool = True,
):
    """
    A combined decorator for CLI utility functions that applies multiple
    validation and error handling decorators.

    This decorator can be used to enhance CLI commands by ensuring that:
    - The client configuration is present and valid.
    - The server connection is healthy before executing the command.
    - Any validation errors from Pydantic models are converted to Typer errors.
    - HTTP 401 Unauthorized errors are handled gracefully, providing user-friendly messages.

    Args:
        func: The function to be decorated. If not provided, the decorator can be used
              as a standalone decorator.
        enable_requires_client_config: If True, applies the `requires_client_config`
                                        decorator to ensure client configuration is valid.
        enable_requires_server_connection: If True, applies the `requires_server_connection`
                                            decorator to check server health.
        enable_validation_err_to_typer_err: If True, applies the `validation_err_to_typer_err`
                                              decorator to convert validation errors.
        enable_http_401_unauthorized_to_typer_err: If True, applies the
                                                    `http_401_unauthorized_to_typer_err`
                                                    decorator to handle unauthorized errors.

    Returns:
        Callable: The decorated function with the applied decorators.
    """

    def decorator(function: Callable) -> Callable:
        # Applying decorators
        if enable_requires_client_config:
            function = requires_client_config(function)
        if enable_requires_server_connection:
            function = requires_server_connection(function)
        if enable_validation_err_to_typer_err:
            function = validation_err_to_typer_err(function)
        if enable_http_401_unauthorized_to_typer_err:
            function = http_401_unauthorized_to_typer_err(function)

        return function

    if func is not None:
        return decorator(func)

    return decorator


ls_format_iter = {
    LsFmtChoices.jsonl: ls_jsonl_format_iter,
    LsFmtChoices.yaml: ls_yaml_format_iter,
}
