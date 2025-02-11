from ast import literal_eval
from typing import Any, Callable, Dict, Iterable, Optional

import typer
from pydantic import BaseModel
from rich.json import JSON


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


def ls_jsonl_format_iter(jsonl_iterator: Iterable[BaseModel], use_rich: bool = True):
    for item in jsonl_iterator:
        json_str = f"{item.model_dump_json(indent=4)}\n"
        if use_rich:
            yield JSON(json_str)
        else:
            yield json_str


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
