import argparse

import click
from pydantic import BaseModel

from labtasker.client.core.cli_utils import LsFmtChoices, ls_format_iter, pager_iterator


class LSResponse(BaseModel):
    """Simulated response model for paginated data."""

    found: bool
    content: list


class Entry(BaseModel):
    """Simulated representing an individual item."""

    id: str
    value: str


def dummy_fetch_function(
    limit: int, offset: int, extra_filter: dict = None
) -> LSResponse:
    """
    Simulate a fetch function that returns a paginated response.

    Args:
        limit (int): The maximum number of items to return.
        offset (int): The starting index for the items.
        extra_filter (dict, optional): Additional filters for the fetch function.

    Returns:
        LSResponse: Paginated response containing the items.
    """
    start = offset
    end = offset + limit
    paginated_items = items[start:end]

    return LSResponse(
        found=bool(paginated_items),
        content=paginated_items,
    )


def main(offset: int, limit: int, mode: str) -> None:
    assert mode in ["jsonl", "yaml"]

    click.echo_via_pager(
        ls_format_iter[LsFmtChoices(mode)](
            pager_iterator(
                fetch_function=dummy_fetch_function, offset=offset, limit=limit
            ),
            use_rich=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--mode", type=str, default="jsonl")

    args = parser.parse_args()

    total_items = args.lines
    items = [Entry(id=str(i), value=f"Item {i}") for i in range(total_items)]

    main(offset=args.offset, limit=args.limit, mode=args.mode)
