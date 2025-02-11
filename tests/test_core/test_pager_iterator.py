import pytest

from labtasker.client.core.cli_utils import pager_iterator


# Dummy fetch function to simulate API behavior
def dummy_fetch_function(limit: int, offset: int, extra_filter: dict = None):
    """Simulate a fetch function that returns a paginated response."""
    total_items = 10  # Total number of items to simulate
    items = [{"id": i, "value": f"value_{i}"} for i in range(total_items)]

    # Calculate the slice of items to return based on limit and offset
    start = offset
    end = offset + limit
    paginated_items = items[start:end]

    # Return a response-like object
    return {
        "found": bool(paginated_items),
        "content": paginated_items,
    }


def test_pager_iterator():
    """Test the pager_iterator function."""
    limit = 3
    offset = 0
    total_items = 10
    items_fetched = []

    for item in pager_iterator(fetch_function=dummy_fetch_function, limit=limit):
        items_fetched.append(item)

    # Check that we fetched the correct number of items
    assert len(items_fetched) == total_items

    # Check the content of the fetched items
    for i, item in enumerate(items_fetched):
        assert item["id"] == i
        assert item["value"] == f"value_{i}"


def test_pager_iterator_empty():
    """Test the pager_iterator with no items."""

    def empty_fetch_function(limit: int, offset: int, extra_filter: dict = None):
        return {
            "found": False,
            "content": [],
        }

    items_fetched = list(pager_iterator(fetch_function=empty_fetch_function, limit=3))
    assert len(items_fetched) == 0
