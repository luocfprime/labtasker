from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select

from labtasker_server.database import Database
from labtasker_server.errors import DomainError
from labtasker_server.filtering import (
    BooleanExpression,
    Comparison,
    FilterPath,
    Membership,
    Presence,
    compile_filter,
    parse_filter,
)
from labtasker_server.models import TaskRow
from labtasker_server.schemas import FailureReport, TaskCreate
from labtasker_server.services.tasks import TaskService
from labtasker_server.validation import MAX_FILTER_BYTES


@pytest.fixture
def task_database(database_path: Path) -> Iterator[Database]:
    database = Database(database_path)
    database.initialize()
    service = TaskService(database)
    tasks = [
        TaskCreate(
            name=None,
            args={},
            metadata={},
            priority=0,
            routes=["old"],
        ),
        TaskCreate(
            name="null",
            args={"x": None, "flag": True},
            metadata={"tags": None, "container": {"key": 1}},
            priority=1,
            routes=["new"],
        ),
        TaskCreate(
            name="number",
            args={"x": 1, "flag": 1, "nested": {"score": 0.5}},
            metadata={"tags": ["baseline", 1]},
            priority=2,
            routes=["new", "old"],
        ),
        TaskCreate(
            name="string",
            args={"x": "1", "flag": False},
            metadata={"tags": ["deprecated"], "container": ["key"]},
            priority=3,
            routes=["other"],
        ),
    ]
    for index, task in enumerate(tasks, start=1):
        service.create("default", f"t_{index:012d}", task)
    try:
        yield database
    finally:
        database.dispose()


def matching_ids(database: Database, expression: str) -> list[str]:
    with database.read_session() as session:
        return list(
            session.scalars(
                select(TaskRow.task_id).where(compile_filter(expression)).order_by(TaskRow.task_id)
            ).all()
        )


def assert_invalid(expression: str, code: str = "invalid_filter") -> DomainError:
    with pytest.raises(DomainError) as raised:
        compile_filter(expression)
    assert raised.value.status_code == 422
    assert raised.value.code == code
    return raised.value


def test_parser_produces_small_validated_ir() -> None:
    assert parse_filter("priority >= -2") == Comparison(FilterPath("priority"), ">=", -2)
    assert parse_filter('"old" in routes') == Membership(
        FilterPath("routes"),
        "in",
        ("old",),
        "array_contains",
    )
    assert parse_filter("missing(args.value)") == Presence(
        FilterPath("args", ("value",)),
        False,
    )
    parsed = parse_filter('status == "pending" and (args.x == 1 or args.x == 2)')
    assert isinstance(parsed, BooleanExpression)
    assert parsed.operator == "and"
    assert len(parsed.children) == 2


def test_missing_null_and_strict_equality_truth_table(task_database: Database) -> None:
    assert matching_ids(task_database, "missing(args.x)") == ["t_000000000001"]
    assert matching_ids(task_database, "exists(args.x)") == [
        "t_000000000002",
        "t_000000000003",
        "t_000000000004",
    ]
    assert matching_ids(task_database, "args.x == None") == ["t_000000000002"]
    assert matching_ids(task_database, "args.x != None") == [
        "t_000000000003",
        "t_000000000004",
    ]
    assert matching_ids(task_database, "args.x == 1") == ["t_000000000003"]
    assert matching_ids(task_database, "args.x == 1.0") == ["t_000000000003"]
    assert matching_ids(task_database, "args.x != 1") == [
        "t_000000000002",
        "t_000000000004",
    ]
    assert matching_ids(task_database, 'args.x == "1"') == ["t_000000000004"]


def test_boolean_is_not_a_json_number(task_database: Database) -> None:
    assert matching_ids(task_database, "args.flag == True") == ["t_000000000002"]
    assert matching_ids(task_database, "args.flag == 1") == ["t_000000000003"]
    assert matching_ids(task_database, "args.flag == False") == ["t_000000000004"]


def test_dynamic_numeric_ordering_requires_present_number(task_database: Database) -> None:
    assert matching_ids(task_database, "args.x >= 1") == ["t_000000000003"]
    assert matching_ids(task_database, "0 < args.nested.score") == ["t_000000000003"]
    assert_invalid('args.x < "2"')
    assert_invalid("args.x < None")
    assert_invalid("args.x < True")


def test_candidate_set_membership_requires_existing_scalar(task_database: Database) -> None:
    assert matching_ids(task_database, 'args.x in [None, 1, "other"]') == [
        "t_000000000002",
        "t_000000000003",
    ]
    assert matching_ids(task_database, "args.x not in [1]") == [
        "t_000000000002",
        "t_000000000004",
    ]
    assert matching_ids(task_database, "args.x in []") == []
    assert matching_ids(task_database, "args.x not in []") == [
        "t_000000000002",
        "t_000000000003",
        "t_000000000004",
    ]


def test_array_and_route_containment_have_explicit_shapes(task_database: Database) -> None:
    assert matching_ids(task_database, '"baseline" in metadata.tags') == ["t_000000000003"]
    assert matching_ids(task_database, '"baseline" not in metadata.tags') == ["t_000000000004"]
    assert matching_ids(task_database, '"key" in metadata.container') == ["t_000000000004"]
    assert matching_ids(task_database, '"key" not in metadata.container') == []
    assert matching_ids(task_database, '"old" in routes') == [
        "t_000000000001",
        "t_000000000003",
    ]
    assert matching_ids(task_database, '"old" not in routes') == [
        "t_000000000002",
        "t_000000000004",
    ]
    assert_invalid("1 in routes")
    assert_invalid('routes in ["old"]')


def test_in_never_means_object_key_membership(task_database: Database) -> None:
    assert matching_ids(task_database, '"key" in metadata.container') == ["t_000000000004"]
    assert matching_ids(task_database, "exists(metadata.container.key)") == ["t_000000000002"]
    assert_invalid('"key" in metadata')


def test_fixed_fields_are_statically_validated(task_database: Database) -> None:
    assert matching_ids(task_database, "priority >= 2") == [
        "t_000000000003",
        "t_000000000004",
    ]
    assert matching_ids(task_database, 'status == "pending"') == [
        "t_000000000001",
        "t_000000000002",
        "t_000000000003",
        "t_000000000004",
    ]
    assert matching_ids(task_database, "name == None") == ["t_000000000001"]
    assert matching_ids(task_database, 'name != "number"') == [
        "t_000000000001",
        "t_000000000002",
        "t_000000000004",
    ]
    assert_invalid("status == 1")
    assert_invalid('priority == "2"')
    assert_invalid('status == "unknown"')
    assert_invalid("id == None")


def test_timestamp_literals_are_strict_rfc3339(task_database: Database) -> None:
    assert len(matching_ids(task_database, 'created_at >= "1970-01-01T00:00:00Z"')) == 4
    assert_invalid('created_at >= "2026-08-20"')
    assert_invalid('created_at >= "2026-08-20T12:00:00"')
    assert_invalid('created_at >= "2026-02-30T12:00:00Z"')
    assert_invalid('created_at >= "2026-08-20T12:00:00.1234567Z"')


def test_last_error_paths_keep_missing_distinct_from_null(task_database: Database) -> None:
    service = TaskService(task_database)
    run_id = "r_000000000001"
    claimed = service.claim("default", "other", run_id)
    assert claimed is not None
    failed_id = claimed.task.id
    service.fail(
        "default",
        failed_id,
        run_id,
        FailureReport(type="Error", message="failed", traceback=None),
    )

    missing_ids = [f"t_{index:012d}" for index in range(1, 5) if f"t_{index:012d}" != failed_id]
    assert matching_ids(task_database, "missing(last_error.type)") == missing_ids
    assert matching_ids(task_database, 'last_error.type != "Other"') == [failed_id]
    assert matching_ids(task_database, 'last_error.type != "Error"') == []
    assert matching_ids(task_database, "last_error.traceback == None") == [failed_id]
    assert matching_ids(task_database, "last_error.traceback != None") == []
    assert matching_ids(task_database, 'last_error.traceback not in ["trace"]') == [failed_id]
    assert matching_ids(
        task_database,
        'last_error.occurred_at >= "1970-01-01T00:00:00Z"',
    ) == [failed_id]


@pytest.mark.parametrize(
    "expression",
    [
        "args.x",
        "not args.x == 1",
        "0 < args.x < 2",
        "args.x == args.y",
        "args.x == [1]",
        "[1] in args.x",
        "1 in [1]",
        "len(args.x) == 1",
        "exists(args.x, args.y)",
        "unknown == 1",
        "args.模型 == 1",
        "args.x-y == 1",
        'args["x"] == 1',
        "True",
    ],
)
def test_ambiguous_or_unsupported_syntax_is_banned(expression: str) -> None:
    assert_invalid(expression)


def test_filter_size_and_numeric_domain_are_bounded() -> None:
    oversized = "x" * (MAX_FILTER_BYTES + 1)
    error = assert_invalid(oversized, code="filter_too_large")
    assert error.details == {"max_bytes": MAX_FILTER_BYTES}
    assert_invalid("priority == 9223372036854775808")
    assert_invalid("priority == -9223372036854775809")
    assert_invalid("args.x == 1e999")
    assert_invalid('args.x == "\ud800"')


def test_syntax_errors_have_a_stable_location() -> None:
    error = assert_invalid("args.x ==")
    assert isinstance(error.details.get("column"), int)
