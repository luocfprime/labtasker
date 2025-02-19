from ast import literal_eval
from enum import Enum
from typing import Any, Callable, Dict, Iterable, Optional

import typer
import yaml
from pydantic import BaseModel
from rich.console import Console
from rich.json import JSON
from rich.syntax import Syntax

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


def ls_jsonl_format_iter(iterator: Iterable[BaseModel], use_rich: bool = True):
    console = Console()
    for item in iterator:
        json_str = f"{item.model_dump_json(indent=4)}\n"
        if use_rich:
            yield JSON(json_str)
        else:
            with console.capture() as capture:
                console.print_json(json_str)
            ansi_str = capture.get()
            yield ansi_str


def ls_yaml_format_iter(iterator: Iterable[BaseModel], use_rich: bool = True):
    console = Console()
    for item in iterator:
        yaml_str = f"{yaml.dump([item.model_dump()], indent=2)}\n"
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


ls_format_iter = {
    LsFmtChoices.jsonl: ls_jsonl_format_iter,
    LsFmtChoices.yaml: ls_yaml_format_iter,
}
