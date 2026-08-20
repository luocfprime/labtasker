from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypeAlias, cast

from sqlalchemy import and_, false, func, not_, or_, select, true
from sqlalchemy.sql.elements import ColumnElement

from labtasker_server.errors import DomainError, invalid
from labtasker_server.models import TaskRouteRow, TaskRow
from labtasker_server.validation import INT64_MAX, INT64_MIN, MAX_FILTER_BYTES

Scalar: TypeAlias = bool | int | float | str | None
CompareOperator: TypeAlias = Literal["==", "!=", "<", "<=", ">", ">="]
MembershipOperator: TypeAlias = Literal["in", "not in"]
PATH_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$")

BUILTIN_TYPES: dict[str, tuple[str, bool]] = {
    "id": ("string", False),
    "status": ("status", False),
    "name": ("string", True),
    "priority": ("number", False),
    "attempt": ("number", False),
    "max_attempts": ("number", False),
    "last_route": ("string", True),
    "created_at": ("timestamp", False),
    "updated_at": ("timestamp", False),
    "started_at": ("timestamp", True),
    "finished_at": ("timestamp", True),
}
LAST_ERROR_TYPES: dict[str, tuple[str, bool, str]] = {
    "type": ("string", False, "type"),
    "message": ("string", False, "message"),
    "traceback": ("string", True, "traceback"),
    "occurred_at": ("timestamp", False, "occurred_at_us"),
    "attempt": ("number", False, "attempt"),
    "run_id": ("string", False, "run_id"),
}
TASK_STATUSES = {"pending", "running", "succeeded", "failed", "cancelled"}


@dataclass(frozen=True, slots=True)
class FilterPath:
    root: str
    segments: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Comparison:
    path: FilterPath
    operator: CompareOperator
    value: Scalar


@dataclass(frozen=True, slots=True)
class Membership:
    path: FilterPath
    operator: MembershipOperator
    values: tuple[Scalar, ...]
    mode: Literal["candidate_set", "array_contains"]


@dataclass(frozen=True, slots=True)
class Presence:
    path: FilterPath
    exists: bool


@dataclass(frozen=True, slots=True)
class BooleanExpression:
    operator: Literal["and", "or"]
    children: tuple[FilterNode, ...]


FilterNode: TypeAlias = Comparison | Membership | Presence | BooleanExpression


@dataclass(frozen=True, slots=True)
class RuntimePath:
    kind: Literal["fixed", "dynamic", "routes"]
    value: Any
    json_type: Any
    declared_type: str | None
    nullable: bool


def parse_filter(expression: str) -> FilterNode:
    if any(0xD800 <= ord(character) <= 0xDFFF for character in expression):
        raise invalid("invalid_filter", "Filter contains a lone Unicode surrogate.")
    if len(expression.encode("utf-8")) > MAX_FILTER_BYTES:
        raise invalid(
            "filter_too_large",
            "Filter exceeds the 8192-byte limit.",
            max_bytes=MAX_FILTER_BYTES,
        )
    if not expression.strip():
        raise invalid("invalid_filter", "Filter must not be empty.")
    try:
        parsed = ast.parse(expression, mode="eval")
        return _parse_expression(parsed.body)
    except (SyntaxError, ValueError, RecursionError) as error:
        details: dict[str, object] = {}
        if isinstance(error, SyntaxError) and error.offset is not None:
            details["column"] = error.offset
        raise invalid("invalid_filter", "Filter syntax is invalid.", **details) from error


def compile_filter(expression: str) -> ColumnElement[bool]:
    try:
        return compile_filter_node(parse_filter(expression))
    except RecursionError as error:
        raise invalid("invalid_filter", "Filter expression is too deeply nested.") from error


def compile_filter_node(node: FilterNode) -> ColumnElement[bool]:
    if isinstance(node, BooleanExpression):
        compiled = [compile_filter_node(child) for child in node.children]
        return and_(*compiled) if node.operator == "and" else or_(*compiled)
    if isinstance(node, Presence):
        runtime = _runtime_path(node.path)
        if runtime.kind in {"fixed", "routes"}:
            return true() if node.exists else false()
        present = runtime.json_type.is_not(None)
        return cast(ColumnElement[bool], present if node.exists else not_(present))
    if isinstance(node, Comparison):
        return _compile_comparison(node)
    if isinstance(node, Membership):
        return _compile_membership(node)
    raise AssertionError(f"Unknown filter node: {node!r}")


def _parse_expression(node: ast.expr) -> FilterNode:
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            bool_operator: Literal["and", "or"] = "and"
        elif isinstance(node.op, ast.Or):
            bool_operator = "or"
        else:
            raise _filter_error(node, "Only 'and' and 'or' Boolean operators are supported.")
        return BooleanExpression(
            bool_operator,
            tuple(_parse_expression(value) for value in node.values),
        )

    if isinstance(node, ast.Call):
        if (
            not isinstance(node.func, ast.Name)
            or node.func.id not in {"exists", "missing"}
            or len(node.args) != 1
            or node.keywords
        ):
            raise _filter_error(node, "Only exists(path) and missing(path) are supported.")
        return Presence(_parse_path(node.args[0]), exists=node.func.id == "exists")

    if not isinstance(node, ast.Compare) or len(node.ops) != 1 or len(node.comparators) != 1:
        raise _filter_error(node, "A filter predicate must be one comparison or membership test.")

    left = node.left
    right = node.comparators[0]
    operator_node = node.ops[0]
    if isinstance(operator_node, (ast.In, ast.NotIn)):
        membership_operator: MembershipOperator = (
            "not in" if isinstance(operator_node, ast.NotIn) else "in"
        )
        left_path = _try_parse_path(left)
        right_path = _try_parse_path(right)
        if left_path is not None and isinstance(right, ast.List):
            return Membership(
                left_path,
                membership_operator,
                tuple(_parse_scalar(element) for element in right.elts),
                "candidate_set",
            )
        if right_path is not None:
            return Membership(
                right_path,
                membership_operator,
                (_parse_scalar(left),),
                "array_contains",
            )
        raise _filter_error(
            node,
            "Membership must be 'path in [values]' or 'value in path'.",
        )

    comparison_operator = _comparison_operator(operator_node, node)
    left_path = _try_parse_path(left)
    right_path = _try_parse_path(right)
    if left_path is not None and right_path is None:
        return Comparison(left_path, comparison_operator, _parse_scalar(right))
    if right_path is not None and left_path is None:
        return Comparison(
            right_path,
            _reverse_operator(comparison_operator),
            _parse_scalar(left),
        )
    raise _filter_error(node, "A comparison must contain exactly one path and one scalar literal.")


def _try_parse_path(node: ast.expr) -> FilterPath | None:
    if not isinstance(node, (ast.Name, ast.Attribute)):
        return None
    return _parse_path(node)


def _parse_path(node: ast.expr) -> FilterPath:
    segments: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        segments.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        raise _filter_error(node, "Filter paths use dot-separated names only.")
    root = current.id
    segments.reverse()

    if root in BUILTIN_TYPES or root == "routes":
        if segments:
            raise _filter_error(node, f"'{root}' does not have nested fields.")
        return FilterPath(root)
    if root not in {"args", "metadata", "result", "last_error"} or not segments:
        raise _filter_error(node, f"Unsupported filter path '{_display_path(root, segments)}'.")
    for segment in segments:
        if not PATH_SEGMENT_RE.fullmatch(segment):
            raise _filter_error(
                node,
                "Path segments must match [A-Za-z_][A-Za-z0-9_]*.",
            )
    if root == "last_error" and (len(segments) != 1 or segments[0] not in LAST_ERROR_TYPES):
        raise _filter_error(node, f"Unsupported filter path '{_display_path(root, segments)}'.")
    return FilterPath(root, tuple(segments))


def _parse_scalar(node: ast.expr) -> Scalar:
    sign = 1
    literal = node
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        sign = -1
        literal = node.operand
    if not isinstance(literal, ast.Constant):
        raise _filter_error(node, "Filter values must be scalar JSON literals.")
    value = literal.value
    if value is None or isinstance(value, (bool, str)):
        if sign == -1:
            raise _filter_error(node, "Only numeric literals may have a minus sign.")
        if isinstance(value, str) and any(
            0xD800 <= ord(character) <= 0xDFFF for character in value
        ):
            raise _filter_error(node, "String literals must contain Unicode scalar values.")
        return value
    if isinstance(value, int):
        value *= sign
        if not INT64_MIN <= value <= INT64_MAX:
            raise _filter_error(node, "Integer literal is outside the signed 64-bit range.")
        return value
    if isinstance(value, float):
        value *= sign
        if not math.isfinite(value):
            raise _filter_error(node, "Number literal must be finite.")
        return value
    raise _filter_error(node, "Filter values must be scalar JSON literals.")


def _comparison_operator(node: ast.cmpop, parent: ast.AST) -> CompareOperator:
    operators: list[tuple[type[ast.cmpop], CompareOperator]] = [
        (ast.Eq, "=="),
        (ast.NotEq, "!="),
        (ast.Lt, "<"),
        (ast.LtE, "<="),
        (ast.Gt, ">"),
        (ast.GtE, ">="),
    ]
    for node_type, name in operators:
        if isinstance(node, node_type):
            return name
    raise _filter_error(parent, "Unsupported comparison operator.")


def _reverse_operator(operator: CompareOperator) -> CompareOperator:
    reversed_operators: dict[CompareOperator, CompareOperator] = {
        "==": "==",
        "!=": "!=",
        "<": ">",
        "<=": ">=",
        ">": "<",
        ">=": "<=",
    }
    return reversed_operators[operator]


def _runtime_path(path: FilterPath) -> RuntimePath:
    if path.root == "routes":
        return RuntimePath("routes", None, None, "array", False)
    if path.root in BUILTIN_TYPES:
        declared_type, nullable = BUILTIN_TYPES[path.root]
        columns = {
            "id": TaskRow.task_id,
            "status": TaskRow.status,
            "name": TaskRow.name,
            "priority": TaskRow.priority,
            "attempt": TaskRow.attempt,
            "max_attempts": TaskRow.max_attempts,
            "last_route": TaskRow.last_route,
            "created_at": TaskRow.created_at_us,
            "updated_at": TaskRow.updated_at_us,
            "started_at": TaskRow.started_at_us,
            "finished_at": TaskRow.finished_at_us,
        }
        return RuntimePath("fixed", columns[path.root], None, declared_type, nullable)

    json_column = {
        "args": TaskRow.args_json,
        "metadata": TaskRow.metadata_json,
        "result": TaskRow.result_json,
        "last_error": TaskRow.last_error_json,
    }[path.root]
    segments = list(path.segments)
    dynamic_declared_type: str | None = None
    nullable = True
    if path.root == "last_error":
        dynamic_declared_type, nullable, stored_name = LAST_ERROR_TYPES[segments[0]]
        segments[0] = stored_name
    json_path = "$" + "".join(f'."{segment}"' for segment in segments)
    return RuntimePath(
        "dynamic",
        func.json_extract(json_column, json_path),
        func.json_type(json_column, json_path),
        dynamic_declared_type,
        nullable,
    )


def _compile_comparison(node: Comparison) -> ColumnElement[bool]:
    runtime = _runtime_path(node.path)
    if runtime.kind == "routes":
        raise _invalid_filter("Routes support membership tests only.")
    if runtime.kind == "fixed" or runtime.declared_type is not None:
        value = _normalize_declared_literal(runtime, node.value)
        return _declared_comparison(runtime, node.operator, value)
    return _dynamic_comparison(runtime, node.operator, node.value)


def _normalize_declared_literal(runtime: RuntimePath, value: Scalar) -> Scalar | int:
    declared_type = runtime.declared_type
    if value is None:
        if runtime.nullable:
            return None
        raise _invalid_filter("A non-nullable field cannot be compared with None.")
    if declared_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise _invalid_filter("This field requires a numeric literal.")
        return value
    if declared_type in {"string", "status"}:
        if not isinstance(value, str):
            raise _invalid_filter("This field requires a string literal.")
        if declared_type == "status" and value not in TASK_STATUSES:
            raise _invalid_filter("Status literal is not a valid Task status.")
        return value
    if declared_type == "timestamp":
        if not isinstance(value, str):
            raise _invalid_filter("Timestamp fields require an RFC 3339 string literal.")
        return _timestamp_us(value)
    raise AssertionError(f"Unknown declared filter type: {declared_type}")


def _declared_comparison(
    runtime: RuntimePath,
    operator: CompareOperator,
    value: Scalar | int,
) -> ColumnElement[bool]:
    column = runtime.value
    if runtime.kind == "dynamic":
        if operator in {"==", "!="}:
            equal = _json_equal(column, runtime.json_type, value)
            if operator == "==":
                return equal
            return and_(runtime.json_type.is_not(None), not_(equal))
        if value is None:
            raise _invalid_filter("None supports only equality and inequality comparisons.")
        expected_types = (
            ["integer", "real"] if runtime.declared_type in {"number", "timestamp"} else ["text"]
        )
        if operator == "<":
            comparison = column < value
        elif operator == "<=":
            comparison = column <= value
        elif operator == ">":
            comparison = column > value
        else:
            comparison = column >= value
        return and_(runtime.json_type.in_(expected_types), comparison)

    if value is None:
        if operator == "==":
            return cast(ColumnElement[bool], column.is_(None))
        if operator == "!=":
            return cast(ColumnElement[bool], column.is_not(None))
        raise _invalid_filter("None supports only equality and inequality comparisons.")
    if operator == "==":
        comparison = column == value
    elif operator == "!=":
        comparison = or_(column.is_(None), column != value) if runtime.nullable else column != value
    elif operator == "<":
        comparison = column < value
    elif operator == "<=":
        comparison = column <= value
    elif operator == ">":
        comparison = column > value
    else:
        comparison = column >= value
    return cast(ColumnElement[bool], comparison)


def _dynamic_comparison(
    runtime: RuntimePath,
    operator: CompareOperator,
    value: Scalar,
) -> ColumnElement[bool]:
    if operator in {"==", "!="}:
        equal = _json_equal(runtime.value, runtime.json_type, value)
        if operator == "==":
            return equal
        return and_(runtime.json_type.is_not(None), not_(equal))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid_filter("Ordering a dynamic JSON path requires a numeric literal.")
    numeric = runtime.json_type.in_(["integer", "real"])
    comparisons = {
        "<": runtime.value < value,
        "<=": runtime.value <= value,
        ">": runtime.value > value,
        ">=": runtime.value >= value,
    }
    return and_(numeric, comparisons[operator])


def _compile_membership(node: Membership) -> ColumnElement[bool]:
    runtime = _runtime_path(node.path)
    if node.mode == "candidate_set":
        if runtime.kind == "routes":
            raise _invalid_filter("Use a scalar literal on the left to test route membership.")
        if runtime.kind == "fixed" or runtime.declared_type is not None:
            normalized = [_normalize_declared_literal(runtime, value) for value in node.values]
            matches = (
                or_(*[_declared_comparison(runtime, "==", value) for value in normalized])
                if normalized
                else false()
            )
            present = true() if runtime.kind == "fixed" else runtime.json_type.is_not(None)
        else:
            comparisons = [
                _json_equal(runtime.value, runtime.json_type, value) for value in node.values
            ]
            matches = or_(*comparisons) if comparisons else false()
            present = runtime.json_type.in_(["null", "true", "false", "integer", "real", "text"])
        return and_(present, not_(matches) if node.operator == "not in" else matches)

    value = node.values[0]
    if runtime.kind == "fixed":
        raise _invalid_filter("The right side of array containment must be an array-valued path.")
    if runtime.kind == "routes":
        if not isinstance(value, str):
            raise _invalid_filter("Route membership requires a string literal.")
        match = _route_exists(value)
        return not_(match) if node.operator == "not in" else match

    each = func.json_each(runtime.value).table_valued("key", "value", "type").alias()
    match = (
        select(1).select_from(each).where(_json_equal(each.c.value, each.c.type, value)).exists()
    )
    is_array = runtime.json_type == "array"
    return and_(is_array, not_(match) if node.operator == "not in" else match)


def _route_exists(route: str) -> ColumnElement[bool]:
    return (
        select(1)
        .select_from(TaskRouteRow)
        .where(
            TaskRouteRow.queue_name == TaskRow.queue_name,
            TaskRouteRow.task_id == TaskRow.task_id,
            TaskRouteRow.route == route,
        )
        .exists()
    )


def _json_equal(value_expression: Any, type_expression: Any, value: Scalar) -> ColumnElement[bool]:
    if value is None:
        return cast(ColumnElement[bool], type_expression == "null")
    if isinstance(value, bool):
        return cast(ColumnElement[bool], type_expression == ("true" if value else "false"))
    if isinstance(value, (int, float)):
        return and_(type_expression.in_(["integer", "real"]), value_expression == value)
    return and_(type_expression == "text", value_expression == value)


def _timestamp_us(value: str) -> int:
    if not RFC3339_RE.fullmatch(value):
        raise _invalid_filter("Timestamp literal must be a strict RFC 3339 string.")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise _invalid_filter("Timestamp literal must be a valid RFC 3339 time.") from error
    if parsed.utcoffset() is None:
        raise _invalid_filter("Timestamp literal must include a UTC offset.")
    delta = parsed.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def _filter_error(node: ast.AST, message: str) -> DomainError:
    details: dict[str, object] = {}
    if hasattr(node, "col_offset"):
        details["column"] = node.col_offset + 1
    return invalid("invalid_filter", message, **details)


def _invalid_filter(message: str) -> DomainError:
    return invalid("invalid_filter", message)


def _display_path(root: str, segments: list[str]) -> str:
    return ".".join([root, *segments])
