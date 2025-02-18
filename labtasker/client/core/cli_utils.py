from ast import literal_eval
from typing import Any, Callable, Dict, Iterable, Optional

import typer
from pydantic import BaseModel
from rich.console import Console
from rich.json import JSON

from labtasker.utils import parse_timeout


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


def ls_jsonl_format_iter(jsonl_iterator: Iterable[BaseModel], use_rich: bool = True):
    console = Console()
    for item in jsonl_iterator:
        json_str = f"{item.model_dump_json(indent=4)}\n"
        if use_rich:
            yield JSON(json_str)
        else:
            with console.capture() as capture:
                console.print_json(json_str)
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
