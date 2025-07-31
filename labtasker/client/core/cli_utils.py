import asyncio
import os
import re
import shlex
import sys
import warnings
from ast import literal_eval
from enum import Enum
from functools import wraps
from shutil import which
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TypeVar, Union

import httpx
import pydantic
import typer
import yaml
from noneprompt import Choice, ListPrompt
from prompt_toolkit import Application
from prompt_toolkit.layout import Float, FloatContainer, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from pydantic import BaseModel
from rich.console import Console
from rich.json import JSON
from rich.syntax import Syntax
from starlette.status import HTTP_401_UNAUTHORIZED

from labtasker.client.core.api import health_check
from labtasker.client.core.config import requires_client_config
from labtasker.client.core.exceptions import (
    LabtaskerNetworkError,
    LabtaskerTypeError,
    LabtaskerValueError,
    QueryTranspilerError,
)
from labtasker.client.core.logging import stderr_console
from labtasker.client.core.utils import transpile_query_safe
from labtasker.utils import parse_time_interval, unflatten_dict

DT = TypeVar("DT")
RT = TypeVar("RT")


class LsFmtChoices(str, Enum):
    jsonl = "jsonl"
    yaml = "yaml"


def parse_dict(d_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Parse metadata string into a dictionary.
    Raise typer.BadParameter if the input is invalid.
    """
    if not d_str:
        return None
    try:
        parsed = literal_eval(d_str)
        if not isinstance(parsed, dict):
            raise ValueError("Input must be a dictionary.")
        return parsed
    except (ValueError, SyntaxError) as e:
        raise typer.BadParameter(f"Invalid dict str: {e}")


def parse_metadata(metadata: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Parse metadata string into a dictionary.
    Raise typer.BadParameter if the input is invalid.
    """
    return parse_dict(d_str=metadata)


def parse_filter(filter_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    1. If provided is a dict, eval it into a python dict mongodb filter using literal_eval
    2. Else, try transpile the string Python expression into mongodb filter
    Args:
        filter_str:

    Returns:

    """
    try:
        return parse_dict(d_str=filter_str)
    except typer.BadParameter:
        try:
            return transpile_query_safe(query_str=filter_str)  # type: ignore[arg-type]
        except QueryTranspilerError as e:
            raise typer.BadParameter(f"Invalid filter str: {e}") from e


def parse_extra_opt(
    args: List[str],
    *,
    ignore_flag_options: bool = True,
    to_primitive: bool = True,
    decompose_dot_separated_options: bool = True,
    normalize_dash: bool = True,
) -> Dict[str, Any]:
    """
    Parses CLI options using shlex for tokenization and regex for pattern matching.

    Args:
        args: A string of CLI options (e.g., "--arg1 foo --arg2 bar -v -abc --flag").
        ignore_flag_options: When set to True, skip flag options (e.g. --verbose, -abc).
                             If False, treat options without values as flags (boolean True).
        to_primitive: Cast the parsed value to Python primitive using ast.literal_eval.
        decompose_dot_separated_options: Decompose dot separated options into nested dict. e.g. --foo.bar hi -> {"foo": {"bar": "hi}}
        normalize_dash: Replace '-' with '_' in the field names. E.g. --foo-bar -> 'foo_bar'

    Returns:
        A parsed nested data dict.
    """
    # Tokenize the input string using shlex
    if isinstance(args, str):
        warnings.warn(
            "Using a string for 'args' is deprecated. Please pass a list of arguments instead.",
            DeprecationWarning,
        )
        tokens = shlex.split(args, posix=os.name == "posix")
    elif isinstance(args, list):
        tokens = args
    else:
        raise LabtaskerTypeError("Invalid type for args. Must be a string or list.")

    parsed_options = {}

    # Regex patterns for different types of arguments
    long_option_pattern = (
        r"^--([a-zA-Z0-9_.-]+)(?:=(.*))?$"
        # Matches --key=value or --key, supports mixed case, dots, underscores, and dashes
    )
    short_option_pattern = r"^-(\w)$"  # Matches -a
    grouped_short_pattern = r"^-(\w{2,})$"  # Matches -abc

    i = 0
    while i < len(tokens):
        token = tokens[i]

        # Match long options (e.g., --foo.bar=value or --foo.bar)
        long_match = re.match(long_option_pattern, token)
        if long_match:
            key, value = long_match.groups()
            if value is None:  # Case: --foo.bar value or --foo.bar
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                    value = tokens[i + 1]
                    i += 1  # Skip the value token
                else:
                    # Handle flags like --foo.bar
                    if ignore_flag_options:
                        i += 1
                        continue
                    value = True

            # Optionally convert the value to a Python primitive type
            if to_primitive and isinstance(value, str):
                try:
                    value = literal_eval(value)
                except (ValueError, SyntaxError):
                    pass  # consider it as a string if it fails to parse as a literal. e.g. "--foo.bar=some-string"

            if normalize_dash:
                key = key.replace("-", "_")

            parsed_options[key] = value
            i += 1
            continue

        # Match single short options (e.g., -a)
        short_match = re.match(short_option_pattern, token)
        if short_match:
            key = short_match.group(1)
            if i + 1 < len(tokens) and not tokens[i + 1].startswith("-"):
                value = tokens[i + 1]
                i += 1  # Skip the value token
            else:
                if ignore_flag_options:
                    i += 1
                    continue
                value = True
            parsed_options[key] = value
            i += 1
            continue

        # Match grouped short options (e.g., -abc)
        grouped_match = re.match(grouped_short_pattern, token)
        if grouped_match:
            for char in grouped_match.group(1):
                if not ignore_flag_options:
                    parsed_options[char] = True
            i += 1
            continue

        # If none of the patterns match, raise an error
        raise LabtaskerValueError(f"Unexpected token: {token}")

    if decompose_dot_separated_options:
        parsed_options = unflatten_dict(parsed_options)

    return parsed_options


def parse_updates(
    updates: List[str],
    top_level_fields: List[str],
    *,
    to_primitive: bool = True,
    normalize_dash: bool = True,
) -> Tuple[List[str], Dict[str, Any]]:
    """

    Args:
        updates: List of string parsed using shlex. Syntax: e.g. ["args.arg1=0", "metadata.label='foo'"]
        top_level_fields: List of string indicating top level field names.
        to_primitive: Cast the parsed value to Python primitive using ast.literal_eval.
        normalize_dash: Turn dash in field names into underscore. E.g. ["args.arg-foo=0"] -> ["args.arg_foo=0"]

    Returns:
        replace_fields: whether fields should be replaced from root
        update_dict: a dict to form TaskUpdateRequest
    """
    parsed_updates = {}
    replace_fields = []

    assign_pattern = r"^(?!-)([a-zA-Z0-9_.-]+)(?:=(.*))?$"  # does not start with '-'

    for update in updates:
        match = re.match(assign_pattern, update)
        if match:
            key, value = match.groups()
            if value is None:
                raise LabtaskerValueError(
                    f"Invalid update: {update}. Got {match.groups()} "
                    f"Updates: {updates}"
                )

            if normalize_dash:
                key = key.replace("-", "_")

            if key in top_level_fields:
                # updates like args={}, that means to replace the whole args
                if to_primitive and isinstance(value, str):
                    try:
                        value = literal_eval(value)
                    except (ValueError, SyntaxError):
                        pass  # consider it as a string if it fails to parse as a literal. e.g. "args.foo=test"
                parsed_updates[key] = value
                replace_fields.append(key)
            else:  # try to split via '.' e.g. args.foo.bar = 0 -> {"args": {"foo.bar" : 0}}
                toplevel, subfields = key.split(".", 1)
                if toplevel in top_level_fields:
                    if toplevel not in parsed_updates:
                        parsed_updates[toplevel] = {}

                    if to_primitive and isinstance(value, str):
                        try:
                            value = literal_eval(value)
                        except (ValueError, SyntaxError):
                            pass  # consider it as a string if it fails to parse as a literal. e.g. "args.foo=test"
                    parsed_updates[toplevel][subfields] = value  # type: ignore[index]
                else:
                    raise LabtaskerValueError(
                        f"Invalid update: {update}. {toplevel} is not in top_level_fields {top_level_fields}. "
                        f"Updates: {updates}"
                    )
        else:
            raise LabtaskerValueError(
                f"Invalid update: {update}, no matching pattern. " f"Updates: {updates}"
            )

    return replace_fields, parsed_updates


def parse_sort(
    sort: Optional[List[str]],
):
    if not sort:
        return []

    s = None
    try:
        result = []
        for s in sort:
            key, order = s.split(":")
            if order == "asc":
                result.append((key, 1))
            elif order == "desc":
                result.append((key, -1))
            else:
                raise typer.BadParameter(f"Invalid order: {order} in sort: {sort}")
        return result
    except ValueError:
        raise typer.BadParameter(f"Invalid sort: {s} in sort: {sort}")


def eta_max_validation(value: Optional[str]):
    if value is None:
        return None
    try:
        parse_time_interval(value)
    except Exception:
        raise typer.BadParameter(
            "ETA max must be a valid duration string (e.g. '1h', '1h30m', '50s')"
        )
    return value


def is_terminal():
    return Console().is_terminal


def confirm(
    *args,
    quiet: bool,
    default: Optional[bool] = False,
    **kwargs,
) -> bool:
    """
    Wraps around
    Args:
        quiet:
        *args:
        default:
        **kwargs:

    Returns:

    """
    if not quiet:
        return typer.confirm(*args, default=default, **kwargs)  # type: ignore[misc]
    else:  # non-interactive script mode
        if default:  # "yes"
            return True

        # "no"
        if kwargs.get("abort", False):
            raise typer.Abort()
        return False


def ls_jsonl_format_iter(
    iterator: Iterable[BaseModel],
    exclude_unset: bool = False,
    use_rich: bool = True,
    ansi: bool = True,
):
    console = Console()
    for item in iterator:
        json_str = item.model_dump_json(indent=4, exclude_unset=exclude_unset) + "\n"

        if not ansi:
            yield json_str
            continue

        if use_rich:
            yield JSON(json_str)
        else:
            with console.capture() as capture:
                console.print_json(json_str)
            ansi_str = capture.get()
            yield ansi_str


def ls_yaml_format_iter(
    iterator: Iterable[BaseModel],
    exclude_unset: bool = False,
    use_rich: bool = True,
    ansi: bool = True,
):
    console = Console()
    for item in iterator:
        yaml_str = (
            yaml.dump(
                [item.model_dump(exclude_unset=exclude_unset)],
                indent=2,
                sort_keys=False,
                allow_unicode=True,
            )
            + "\n"
        )

        if not ansi:
            yield yaml_str
            continue

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


def is_piped_io():
    return not sys.stdin.isatty() or not sys.stdout.isatty()


def get_editor(editor: Optional[str] = None) -> str:
    """
    Get system default editor.
    Adapted from https://github.com/pallets/click/blob/a8b41c077b225c30921a78190507a463a20ebb1b/src/click/_termui_impl.py#L567
    """
    if editor is not None:
        return editor
    for key in "VISUAL", "EDITOR":
        rv = os.environ.get(key)
        if rv:
            return rv
    if sys.platform.startswith("win"):
        return "notepad"
    for editor in "sensible-editor", "vim", "nano":
        if which(editor) is not None:
            return editor
    return "vi"


def requires_server_connection(func: Optional[Callable] = None, /):
    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                status = health_check()
                assert status.status == "healthy"
            except (AssertionError, LabtaskerNetworkError) as e:
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


def handle_http_err(
    func: Optional[Callable] = None,
    /,
    *,
    status_code: int,
    err_handler: Callable[[httpx.HTTPStatusError], None],
):
    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == status_code:
                    err_handler(e)
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

            def error_401_handler(e):
                stderr_console.print(
                    f"[bold red]Error:[/bold red] Either invalid credentials or queue not created. "
                    f"Please check your configuration. Detail: {e}"
                )
                raise typer.Abort()

            function = handle_http_err(
                function,
                status_code=HTTP_401_UNAUTHORIZED,
                err_handler=error_401_handler,
            )

        return function

    if func is not None:
        return decorator(func)

    return decorator


class TimedListPrompt(ListPrompt):
    """A ListPrompt with countdown and timeout functionality."""

    def __init__(
        self,
        *args,
        timeout: int = 10,
        default: Optional[Choice] = None,
        keyboard_interrupt_default: Optional[Choice] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.timeout = timeout
        self.default = default
        self.keyboard_interrupt_default = keyboard_interrupt_default
        self.countdown_text = [
            ("class:countdown", "TIMER: "),
            ("class:countdown-emphasis", f"{timeout}"),
            ("class:countdown", " seconds remaining"),
        ]

    def _build_layout(self) -> Layout:
        layout = super()._build_layout()
        float_container = FloatContainer(
            content=layout.container, floats=[]  # Initialize with empty floats list
        )

        # Add countdown timer float
        float_container.floats.append(
            Float(
                Window(
                    FormattedTextControl(lambda: self.countdown_text),
                    height=1,
                    dont_extend_height=True,
                    always_hide_cursor=True,
                ),
                top=0,
                right=0,
            )
        )
        return Layout(container=float_container)

    def _build_style(self, style: Style) -> Style:
        base_style = super()._build_style(style)
        return Style(
            [
                *base_style.style_rules,
                ("countdown", "fg:ansiyellow bold"),
                ("countdown-emphasis", "fg:ansired blink bold"),
                ("timeout-message", "fg:#FF0000 bg:#000000 bold"),
            ]
        )

    async def _run_countdown(self, app: Application):
        for i in range(self.timeout, 0, -1):
            self.countdown_text = [
                ("class:countdown", "TIME REMAINING: "),
                ("class:countdown-emphasis", f"{i}"),
                ("class:countdown", " seconds"),
            ]
            app.invalidate()
            await asyncio.sleep(1)
        self.countdown_text = [
            ("class:timeout-message", "TIME'S UP! SETTING TO DEFAULT...")
        ]
        app.exit(result=None)

    async def prompt_async(self, **kwargs) -> Union[Choice, None]:  # type: ignore[override]
        app = self._build_application(no_ansi=False, style=Style([]))
        countdown_task = asyncio.create_task(self._run_countdown(app))

        result = await app.run_async()
        countdown_task.cancel()
        if result is None:  # timed out
            return self.default
        elif isinstance(result, type(...)):  # keyboard interrupt
            return self.keyboard_interrupt_default
        else:
            return result


def make_a_choice(
    question: str,
    options: List[Choice],
    default: Choice,
    keyboard_interrupt_default: Choice,
    timeout: int = 10,
) -> Optional[Choice]:
    """Helper function to create and run a timed choice prompt."""
    prompt = TimedListPrompt(
        question,
        choices=options,
        timeout=timeout,
        default=default,
        keyboard_interrupt_default=keyboard_interrupt_default,
    )

    try:
        return asyncio.run(prompt.prompt_async())
    except Exception:  # EOFError:  # e.g. closed connection under special circumstances
        return default


ls_format_iter = {
    LsFmtChoices.jsonl: ls_jsonl_format_iter,
    LsFmtChoices.yaml: ls_yaml_format_iter,
}
