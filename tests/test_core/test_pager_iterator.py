import pytest
from pydantic import BaseModel

from labtasker.client.core.cli_utils import pager_iterator

pytestmark = [pytest.mark.unit]


class LSResponse(BaseModel):
    """Response model for paginated data."""

    found: bool
    content: list


class Entry(BaseModel):
    """Model representing an individual item."""

    id: str
    value: str


# Dummy fetch function to simulate API behavior
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
    total_items = 10  # Total number of items to simulate
    items = [Entry(id=str(i), value=f"value_{i}") for i in range(total_items)]

    # Calculate the slice of items to return based on limit and offset
    start = offset
    end = offset + limit
    paginated_items = items[start:end]

    return LSResponse(
        found=bool(paginated_items),
        content=paginated_items,
    )


def test_pager_iterator():
    """Test the pager_iterator function."""
    limit = 3
    offset = 0
    total_items = 10
    items_fetched = []

    # Use the pager_iterator to fetch items
    for item in pager_iterator(fetch_function=dummy_fetch_function, limit=limit):
        items_fetched.append(item)

    # Check that the correct number of items was fetched
    assert len(items_fetched) == total_items

    # Check the content of the fetched items
    for i, item in enumerate(items_fetched):
        assert item.id == str(i)
        assert item.value == f"value_{i}"


def test_pager_iterator_empty():
    """Test the pager_iterator with no items."""

    def empty_fetch_function(
        limit: int, offset: int, extra_filter: dict = None
    ) -> LSResponse:
        """
        Fetch function that simulates no items being returned.

        Args:
            limit (int): The maximum number of items to return.
            offset (int): The starting index for the items.
            extra_filter (dict, optional): Additional filters for the fetch function.

        Returns:
            LSResponse: Empty response.
        """
        return LSResponse(
            found=False,
            content=[],
        )

    # Use the pager_iterator with an empty fetch function
    items_fetched = list(pager_iterator(fetch_function=empty_fetch_function, limit=3))

    # Assert no items were fetched
    assert len(items_fetched) == 0
