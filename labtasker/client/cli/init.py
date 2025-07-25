"""
Implements `labtasker init`
"""

import traceback
from functools import wraps
from shutil import rmtree
from typing import Callable, Optional, Tuple

import httpx
import pydantic
import tomlkit
import typer
from noneprompt import CancelledError, Choice, ConfirmPrompt, InputPrompt, ListPrompt
from pydantic import HttpUrl, SecretStr
from starlette.status import HTTP_409_CONFLICT

from labtasker.client.cli.cli import app
from labtasker.client.core.api import create_queue, get_queue, health_check
from labtasker.client.core.config import (
    ClientConfig,
    EndpointConfig,
    QueueConfig,
    init_labtasker_root,
)
from labtasker.client.core.exceptions import (
    LabtaskerHTTPStatusError,
    LabtaskerNetworkError,
)
from labtasker.client.core.logging import stderr_console, stdout_console
from labtasker.client.core.paths import (
    get_labtasker_client_config_path,
    get_labtasker_root,
)
from labtasker.security import get_auth_headers


class _GoToLoopStart(Exception):
    pass


def _cancelled_err_to_aborted(func: Optional[Callable] = None, /):
    """Cast CancelledError triggered by CTRL+C to typer.Abort"""

    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except CancelledError:
                raise typer.Abort()

        return wrapped

    if func is None:
        return decorator

    return decorator(func)


def _input_loop(func: Callable, /):
    @wraps(func)
    def inner(*args, **kwargs):
        while True:
            try:
                return func(*args, **kwargs)
            except _GoToLoopStart:
                continue

    return inner


@_input_loop
def setup_endpoint_url() -> Tuple[str, bool]:
    def validator(value: str) -> bool:
        try:
            EndpointConfig.__pydantic_validator__.validate_assignment(
                EndpointConfig.model_construct(), "api_base_url", value
            )
            return True
        except pydantic.ValidationError:
            return False

    # 1. Prompt
    url = InputPrompt(
        "URL of your Labtasker server: ",
        default_text="http://localhost:9321",
        validator=validator,
    ).prompt()
    url = str(HttpUrl(url))

    # 2. validate connection
    try:
        resp = health_check(client=httpx.Client(base_url=url))
        if resp.status == "healthy":
            return url, True
    except LabtaskerNetworkError:
        pass

    choice = ListPrompt(
        "The connection to the server is unhealthy. What would you like to do?",
        choices=[
            Choice("Edit the URL", data="edit"),
            Choice("Proceed with next step", data="next"),
            Choice("Abort", data="abort"),
        ],
    ).prompt()

    if choice.data == "edit":
        raise _GoToLoopStart()
    elif choice.data == "next":
        return url, False
    else:
        raise typer.Abort()


@_input_loop
def setup_queue_name() -> str:
    def validator(value: str) -> bool:
        try:
            QueueConfig.__pydantic_validator__.validate_assignment(
                QueueConfig.model_construct(), "queue_name", value
            )
            return True
        except pydantic.ValidationError:
            return False

    queue_name = InputPrompt(
        "Queue name (just like a 'username' or 'project_name') : ",
        validator=validator,
        error_message="Queue name should be a valid string without spaces. ^[a-zA-Z0-9_-]+$",
    ).prompt()
    return queue_name


@_input_loop
def setup_password() -> str:
    def validator(value: str) -> bool:
        try:
            QueueConfig.__pydantic_validator__.validate_assignment(
                QueueConfig.model_construct(), "password", SecretStr(value)
            )
            return True
        except pydantic.ValidationError:
            return False

    first_input = InputPrompt(
        "Input the password for your queue: ",
        validator=validator,
        is_password=True,
    ).prompt()

    second_input = InputPrompt(
        "(confirm) Input the password again: ",
        validator=validator,
        is_password=True,
    ).prompt()

    if first_input != second_input:
        stderr_console.print("The passwords do not match. Please try again.")
        raise _GoToLoopStart()

    return first_input


@_input_loop
def setup_queue(base_url, base_url_verified) -> Tuple[str, str]:
    queue_name = setup_queue_name()
    password = setup_password()

    if not base_url_verified:
        return queue_name, password

    # Try to create the queue (or verify its existence) if the
    # base url connection is available
    auth_headers = get_auth_headers(queue_name, SecretStr(password))
    client = httpx.Client(
        base_url=base_url,
        headers={**auth_headers, "Content-Type": "application/json"},
    )

    # see if the queue already exists
    try:
        get_queue(client=client)
        # queue exists and verified
        return queue_name, password
    except LabtaskerHTTPStatusError:
        pass

    yes = ConfirmPrompt(
        question="Would you like to create this queue?", default_choice=True
    ).prompt()
    if yes:
        try:
            resp = create_queue(queue_name, password, client=client)
            stdout_console.print(resp)
            return queue_name, password
        except LabtaskerHTTPStatusError as e:
            if e.response.status_code == HTTP_409_CONFLICT:
                stderr_console.print(
                    f"Queue '{queue_name}' already exists. Please try another name."
                )
                raise _GoToLoopStart()
            else:
                raise e

    return queue_name, password


@_input_loop
def confirm_set_traceback_filter() -> bool:
    choices = [
        Choice(
            "No: I want more compatibility than security.",
            data=False,
        ),
        Choice(
            "Yes: I want better exception formatting and sensitive text filtering.",
            data=True,
        ),
    ]
    choice = ListPrompt(
        "Enable traceback hook? (Overrides the `sys.excepthook`)", choices=choices
    ).prompt()

    return choice.data


@app.command()
@_cancelled_err_to_aborted
def init():
    """Set up Labtasker client configuration interactively.

    This command guides you through the process of:
    - Connecting to a Labtasker server
    - Creating or selecting a task queue
    - Setting up authentication
    - Configuring client behavior

    Run this command before using other Labtasker commands.
    """
    # 0. Check if Labtasker root exists
    if get_labtasker_root().exists():
        stderr_console.print(
            f"Labtasker root directory at {get_labtasker_root()} already exists. "
            "You can use `labtasker config` to modify your configuration, "
            "or delete it and try `labtasker init` to reinitialize it. "
            f"Note: deleting the {get_labtasker_root()} will also delete the run logs inside it."
        )
        raise typer.Abort()

    # 1. Setup url
    url, verified = setup_endpoint_url()

    # 2. Setup queue name
    queue_name, password = setup_queue(base_url=url, base_url_verified=verified)

    # 3. Traceback filter
    enable_traceback_filter = confirm_set_traceback_filter()

    # 4. Create config file
    init_labtasker_root()
    try:
        with open(get_labtasker_client_config_path(), "r", encoding="utf-8") as f:
            config = ClientConfig.model_validate(tomlkit.load(f))

        config.endpoint.api_base_url = HttpUrl(url)
        config.queue.queue_name = queue_name
        config.queue.password = SecretStr(password)
        config.enable_traceback_filter = enable_traceback_filter

        # Some of the fields needs manual serialization
        config_dict = config.model_dump()
        config_dict["endpoint"]["api_base_url"] = url
        config_dict["queue"]["password"] = password

        with open(get_labtasker_client_config_path(), "w", encoding="utf-8") as f:
            tomlkit.dump(config_dict, f)
    except Exception as e:
        stderr_console.print(
            f"An unexpected error occurred: {e}.\n" f"Detail: {traceback.format_exc()}"
        )
        rmtree(get_labtasker_root())

    stdout_console.print(
        f"[bold green]Configuration initialized successfully at {get_labtasker_client_config_path()}.[/bold green]"
    )
