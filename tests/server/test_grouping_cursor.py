from __future__ import annotations

import pytest

from labtasker_server.errors import DomainError
from labtasker_server.grouping import decode_position, encode_position


def test_long_valid_filter_can_round_trip_group_cursor() -> None:
    selection = {
        "operation": "tasks.count",
        "queue": "default",
        "filter": 'status == "pending"' + "\t" * 7000,
        "group_by": ["routes", "status"],
    }
    cursor = encode_position(selection, ["a", "pending"])
    assert len(cursor) < 1024
    assert decode_position(cursor, selection, 2) == ["a", "pending"]
    assert decode_position(cursor, dict(reversed(list(selection.items()))), 2) == ["a", "pending"]


@pytest.mark.parametrize(
    "change",
    [
        {"queue": "other"},
        {"filter": 'status == "pending" '},
        {"group_by": ["status", "routes"]},
        {"operation": "workers.count"},
    ],
)
def test_compact_cursor_still_binds_exact_selection(change: dict[str, object]) -> None:
    selection = {
        "operation": "tasks.count",
        "queue": "default",
        "filter": 'status == "pending"',
        "group_by": ["routes", "status"],
    }
    cursor = encode_position(selection, ["a", "pending"])
    with pytest.raises(DomainError) as raised:
        decode_position(cursor, {**selection, **change}, 2)
    assert raised.value.code == "invalid_cursor"
