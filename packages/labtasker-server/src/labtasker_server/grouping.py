from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

from sqlalchemy import Select, and_, func, or_
from sqlalchemy.orm import Session

from labtasker_server.errors import invalid
from labtasker_server.schemas import CountGroup, GroupCountPage


def request_error(field: str, message: str) -> None:
    raise invalid(
        "invalid_request",
        "Request validation failed.",
        errors=[{"location": ["query", field], "message": message}],
    )


def grouping_fields(
    value: str | None, allowed: set[str], limit: int | None, cursor: str | None
) -> list[str] | None:
    if value is None:
        if limit is not None or cursor is not None:
            request_error("group_by", "Pagination requires group_by.")
        return None
    fields = value.split(",")
    if (
        not value
        or any(c.isspace() for c in value)
        or len(set(fields)) != len(fields)
        or any(field not in allowed for field in fields)
    ):
        request_error("group_by", "Use distinct supported fields, comma-separated with no spaces.")
    page_limit(limit)
    return fields


def page_limit(value: int | None) -> int:
    if value is None:
        return 100
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        request_error("limit", "Expected an integer from 1 through 1000.")
    return value


def _selection_digest(selection: dict[str, Any]) -> str:
    # Bind exact selectors without copying potentially large/escaped filters
    # into every cursor. This is a query fingerprint, not an authentication token.
    raw = json.dumps(selection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def encode_position(selection: dict[str, Any], values: list[str]) -> str:
    raw = json.dumps(
        {"v": 1, "selection": _selection_digest(selection), "position": values},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_position(token: str | None, selection: dict[str, Any], width: int) -> list[str] | None:
    if token is None:
        return None
    try:
        if not token or len(token) > 16384 or not token.isascii():
            raise ValueError
        raw = base64.b64decode(token + "=" * (-len(token) % 4), altchars=b"-_", validate=True)
        value = json.loads(raw)
        if (
            not isinstance(value, dict)
            or set(value) != {"v", "selection", "position"}
            or type(value["v"]) is not int
            or value["v"] != 1
            or value["selection"] != _selection_digest(selection)
        ):
            raise ValueError
        position = value["position"]
        if (
            not isinstance(position, list)
            or len(position) != width
            or any(
                not isinstance(item, str)
                or not item
                or any(0xD800 <= ord(c) <= 0xDFFF for c in item)
                for item in position
            )
        ):
            raise ValueError
        return position
    except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError) as error:
        raise invalid(
            "invalid_cursor", "Cursor is malformed or does not match this request."
        ) from error


def after_keys(columns: list[Any], values: list[str]) -> Any:
    return or_(
        *(
            and_(*(columns[j] == values[j] for j in range(i)), column > values[i])
            for i, column in enumerate(columns)
        )
    )


def grouped_page(
    session: Session,
    source: Select[Any],
    columns: dict[str, Any],
    fields: list[str],
    selection: dict[str, Any],
    count: int,
    limit: int | None,
    cursor: str | None,
) -> GroupCountPage:
    size = page_limit(limit)
    keys = [columns[field] for field in fields]
    position = decode_position(cursor, selection, len(fields))
    query = source.with_only_columns(*keys, func.count()).group_by(*keys).order_by(*keys)
    if position is not None:
        query = query.where(after_keys(keys, position))
    rows = session.execute(query.limit(size + 1)).all()
    items = [
        CountGroup(key=dict(zip(fields, row[:-1], strict=True)), count=row[-1])
        for row in rows[:size]
    ]
    next_cursor = None
    if len(rows) > size:
        next_cursor = encode_position(selection, list(rows[size - 1][:-1]))
    return GroupCountPage(group_by=fields, count=count, items=items, next_cursor=next_cursor)
