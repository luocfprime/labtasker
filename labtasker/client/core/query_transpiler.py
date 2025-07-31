import ast
import difflib
from datetime import timezone
from typing import Any, Dict, List, NoReturn, Optional, Type

import dateparser
from rich.console import Console
from rich.text import Text

from labtasker.client.core.exceptions import (
    QueryTranspilerError,
    QueryTranspilerSyntaxError,
    QueryTranspilerValueError,
)
from labtasker.client.core.logging import stderr_console


def format_print_error(
    console: Console,
    line: int,
    column: int,
    error_line: str,
    msg: str,
    context_size: int = 50,
) -> None:
    """
    Format and print an error message with context using Rich for enhanced terminal output.

    Args:
        console (Console): The Rich console instance for output.
        line (int): The line number where the error occurred.
        column (int): The column number where the error occurred.
        error_line (str): The complete line of text containing the error.
        msg (str): The error message to display.
        context_size (int, optional): Number of characters to show around the error. Defaults to 50.
    """
    # Determine the start and end positions for the context
    start = max(0, column - context_size)  # Ensure start is non-negative
    end = min(
        len(error_line), column + context_size + 1
    )  # Ensure end doesn't exceed line length

    # Extract the context line
    context_line = error_line[start:end]

    # Add ellipses to indicate truncation
    if start > 0:
        context_line = f"...{context_line}"  # Add "..." at the beginning if truncated
    if end < len(error_line):
        context_line = f"{context_line}..."  # Add "..." at the end if truncated

    # Calculate pointer offset for the truncated context
    pointer_offset = (
        column - start + (3 if start > 0 else 0)
    )  # Adjust for "..." at the start
    pointer = " " * pointer_offset + "^"

    # Use Rich's Text objects instead of f-strings to avoid markup parsing issues
    error_title = Text(
        f"Error when parsing query at line {line}, column {column + 1}:",
        style="bold red",
    )

    context_header = Text("Err context: ", style="bold orange1")
    context_content = Text(context_line)
    context_line_display = Text.assemble(context_header, context_content)

    pointer_line = Text(
        f"{' ' * len(context_header)}{pointer}  <-- Error here (Column: {column + 1})"
    )
    pointer_line.stylize("bright_red", pointer_offset + 11, pointer_offset + 12)
    pointer_line.stylize("bold red", pointer_offset + 15, len(pointer_line))

    error_msg_header = Text("Error: ", style="bold red")
    error_msg_content = Text(msg)
    error_msg_display = Text.assemble(error_msg_header, error_msg_content)

    # Print the complete error message
    console.print(error_title)
    console.print(context_line_display)
    console.print(pointer_line)
    console.print(error_msg_display)
    console.print()  # Add a blank line for better readability


def _is_field(n):
    """Valid field.
    Examples:
        foo
        foo.bar
        foo[0]
        foo['bar']
        foo.bar[0]
        foo['bar'].baz
    """
    return (
        isinstance(n, ast.Name)
        or isinstance(n, ast.Attribute)
        or isinstance(n, ast.Subscript)
    )


def _is_literal(n):
    """
    Check if an AST node represents a literal value (constant, dict, list, etc.)
    """
    return (
        isinstance(n, ast.Constant)
        or isinstance(n, ast.Dict)
        or isinstance(n, ast.Tuple)
        or isinstance(n, ast.List)
        or isinstance(n, ast.Set)
    )


def _is_unary_sub(n: ast.expr):
    return isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub)


def _is_negative_constant(n: ast.expr):
    return (
        isinstance(n, ast.UnaryOp)
        and isinstance(n.op, ast.USub)
        and isinstance(n.operand, ast.Constant)
    )


class QueryTranspiler(ast.NodeVisitor):
    """Parses logical expression strings into MongoDB queries, supporting various operators"""

    # Binary comparison operator mapping: Python operator -> MongoDB operator
    COMPARE_OP_MAP = {
        ast.Gt: "$gt",  # a > b -> {a: {$gt: b}}
        ast.GtE: "$gte",  # a >= b -> {a: {$gte: b}}
        ast.Lt: "$lt",  # a < b -> {a: {$lt: b}}
        ast.LtE: "$lte",  # a <= b -> {a: {$lte: b}}
        ast.Eq: "$eq",  # a == b -> {a: b} or {a: {$eq: b}}
        # ast.NotEq: "$ne",  # a != b -> {a: {$ne: b}} (not supported due to ambiguity)
    }

    # Binary comparison operator inversions (for value-field comparisons)
    INVERTED_OP_MAP = {
        ast.Gt: ast.Lt,  # 1 > field -> field < 1
        ast.GtE: ast.LtE,  # 1 >= field -> field <= 1
        ast.Lt: ast.Gt,  # 1 < field -> field > 1
        ast.LtE: ast.GtE,  # 1 <= field -> field >= 1
        # These remain the same when inverted
        ast.Eq: ast.Eq,  # 1 == field -> field == 1
        ast.NotEq: ast.NotEq,  # 1 != field -> field != 1
    }

    # Logical operator mapping: Python operator -> MongoDB operator
    LOGICAL_OP_MAP = {
        ast.And: "$and",  # a and b -> {$and: [a, b]}
        ast.Or: "$or",  # a or b -> {$or: [a, b]}
    }

    def __init__(self, query_str: str, allowed_fields: Optional[List[str]] = None):
        super().__init__()
        self.query_str = query_str
        self.allowed_fields = allowed_fields

    def _report_error(
        self, node: ast.AST, msg: str, exception: Type[QueryTranspilerError]
    ) -> NoReturn:
        """
        Report an error with context from the AST node before raising an exception.

        Args:
            node: The AST node where the error occurred
            msg: The error message
        """
        # Extract line and column from the node
        line_no = getattr(node, "lineno", 1)
        col_no = getattr(node, "col_offset", 0)

        # Get the error line from the query string
        lines = self.query_str.split("\n")
        if line_no <= len(lines):
            error_line = lines[line_no - 1]
        else:
            error_line = self.query_str

        # Format and print the error
        format_print_error(
            console=stderr_console,
            line=line_no,
            column=col_no,
            error_line=error_line,
            msg=msg,
        )

        raise exception(msg)

    def visit(self, node: Any) -> Any:
        """
        Visit a node and return the MongoDB query representation.
        This method overrides the parent method to provide proper typing.
        """
        return super().visit(node)

    def visit_Module(self, node: ast.Module) -> Dict[str, Any]:
        """
        Process the root of the AST (the module node) to make sure the input is an expression
        """
        if node.body:
            if isinstance(node.body[0], ast.Expr):
                # It's an expression, process normally
                return self.visit(node.body[0].value)  # type: ignore
            elif isinstance(node.body[0], ast.Assign):
                # It's an assignment, provide a helpful error message
                assignment = node.body[0]
                target_name = ""
                if isinstance(assignment.targets[0], ast.Name):  # type: ignore
                    target_name = assignment.targets[0].id  # type: ignore

                # Get the original line with the assignment
                line_no = getattr(assignment, "lineno", 1)
                lines = self.query_str.split("\n")
                error_line = (
                    lines[line_no - 1] if line_no <= len(lines) else self.query_str
                )

                # Create suggestion with == instead of =
                suggestion = error_line.replace("=", "==", 1)

                self._report_error(
                    node=assignment.targets[0],  # type: ignore
                    msg=f"Assignment '{target_name} = ...' not allowed in query. "
                    f"If you meant to check equality, use '==' instead of '='. "
                    f"Suggested correction: {suggestion}",
                    exception=QueryTranspilerValueError,
                )

        # If we get here, there was other issue
        self._report_error(
            node=node,
            msg="Expected an expression in the module",
            exception=QueryTranspilerValueError,
        )

    def visit_BoolOp(self, node: ast.BoolOp) -> Dict[str, Any]:
        """
        Process boolean operations (AND, OR)
        Python: a and b and c or a or b
        MongoDB: {$and: [a, b, c]} or {$or: [a, b]}
        """
        op_type = type(node.op)
        mongo_op = self.LOGICAL_OP_MAP.get(op_type)  # type: ignore

        if not mongo_op:
            self._report_error(
                node=node,
                msg=f"Unsupported logical operator: {op_type}",
                exception=QueryTranspilerValueError,
            )

        operands = [self.visit(value) for value in node.values]
        return {mongo_op: operands}

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Dict[str, Any]:
        """
        Process unary operations, mainly NOT
        Python: not a
        MongoDB: {$not: a}
        """
        if isinstance(node.op, ast.Not):
            # operand = self.visit(node.operand)
            # return {"$not": operand}
            self._report_error(
                node=node,
                msg="'not' is not supported, as it may lead to ambiguous behaviour due to the missing key returning null problem. "
                "If you wish to use $ne, use the full mongodb query and handle the $exists manually",
                exception=QueryTranspilerValueError,
            )

        self._report_error(
            node=node,
            msg=f"Unsupported unary operator: {type(node.op)}",
            exception=QueryTranspilerValueError,
        )

    def visit_Compare(self, node: ast.Compare) -> Dict[str, Any]:
        """
        Process comparison operations (>, >=, <, <=, ==, !=, in, not in)
        Python: a > b, x == y, value in [1, 2], "tag" not in ["foo", "bar"], "key" in dict(obj.field)
        MongoDB: Various forms depending on context
        """
        # Check for chained comparisons
        if len(node.ops) > 1 or len(node.comparators) > 1:
            self._report_error(
                node=node,
                msg="Chained comparisons not supported (e.g., a < b < c)",
                exception=QueryTranspilerValueError,
            )

        left = node.left
        op = node.ops[0]
        right = node.comparators[0]

        if isinstance(op, ast.NotEq):
            self._report_error(
                node=node,
                msg="'!=' operator is not supported, as it may lead to ambiguous behaviour due to the missing key returning null problem. "
                "If you wish to use $ne, use the full mongodb query and handle the $exists manually",
                exception=QueryTranspilerValueError,
            )

        # Handle membership tests (in, not in)
        if isinstance(op, ast.In):
            return self._handle_in_operator(node, left, right)
        elif isinstance(op, ast.NotIn):
            return self._handle_not_in_operator(node, left, right)

        # Handle other comparison operators
        return self._handle_comparison_operator(node, left, op, right)

    def _handle_in_operator(
        self, node: ast.Compare, left: ast.expr, right: ast.expr
    ) -> Dict[str, Any]:
        """Handle various cases for the 'in' operator"""
        left_value = self.visit(left)

        if _is_field(right):
            self._report_error(
                node=node,
                msg="Ambiguous expression. To use `'foo' in foo.bar`, "
                "you must specify the type of foo.bar via `'foo' in list(foo.bar)` or `'foo' in dict(foo.bar)`",
                exception=QueryTranspilerValueError,
            )

        # Handle case where right side is a function call like list(foo.bar) or dict(foo.bar)
        if isinstance(right, ast.Call):
            return self._handle_function_call_in_membership(
                node, left, right, is_not_in=False
            )

        right_value = self.visit(right)

        # Special case: "value" in field - value contained in array field
        if _is_literal(left) and _is_field(right):
            return {right_value: left_value}
        elif _is_literal(right) and _is_field(left):
            # Standard case: field in [values]
            return {left_value: {"$in": right_value}}
        else:
            self._report_error(
                node=node,
                msg="For 'field in [literals]' pattern or literal in dict(field) pattern, both sides must be either a field or a list of literals",
                exception=QueryTranspilerValueError,
            )

    def _handle_not_in_operator(
        self, node: ast.Compare, left: ast.expr, right: ast.expr
    ) -> Dict[str, Any]:
        """Handle various cases for the 'not in' operator"""
        self._report_error(
            node=node,
            msg="'not in' operator is not supported, as it may lead to ambiguous behaviour due to the missing key returning null problem. "
            "If you wish to use $nin, use the full mongodb query and handle the $exists manually",
            exception=QueryTranspilerValueError,
        )
        # left_value = self.visit(left)
        #
        # # Handle case where right side is a function call like list(foo.bar) or dict(foo.bar)
        # if isinstance(right, ast.Call):
        #     return self._handle_function_call_in_membership(
        #         node, left, right, is_not_in=True
        #     )
        #
        # right_value = self.visit(right)
        #
        # # Special case: "value" not in field - value not contained in array field
        # if _is_literal(left) and _is_field(right):
        #     return {right_value: {"$ne": left_value}}
        #
        # # Standard case: field not in [values]
        # return {left_value: {"$nin": right_value}}

    def _handle_function_call_in_membership(
        self, node: ast.Compare, left: ast.expr, right: ast.Call, is_not_in: bool
    ) -> Dict[str, Any]:
        """Handle function calls in membership tests (list/dict functions)"""
        if is_not_in:
            self._report_error(
                node=node,
                msg="'not in' operator is not supported, as it may lead to ambiguous behaviour due to the missing key returning null problem. "
                "If you wish to use $nin, use the full mongodb query and handle the $exists manually",
                exception=QueryTranspilerValueError,
            )
        # Only handle built-in functions like list() and dict() specially
        if not isinstance(right.func, ast.Name) or right.func.id not in (
            "list",
            "dict",
        ):
            # For other function calls, use the generic handling
            self._report_error(
                node=node,
                msg=f"Expected function call like list(foo.bar) or dict(foo.bar), got {right.func}",
                exception=QueryTranspilerValueError,
            )

        if (
            right.func.id == "list"
            and len(right.args) == 1
            and _is_field(right.args[0])
        ):
            # Handle special case: "value" in/not in list(foo.bar)
            field_value = self.visit(right.args[0])
            left_value = self.visit(left)
            # operator = "$ne" if is_not_in else ""
            # return (
            #     {field_value: {"$ne": left_value}}
            #     if is_not_in
            #     else {field_value: left_value}
            # )
            return {field_value: left_value}

        elif (
            right.func.id == "dict"
            and len(right.args) == 1
            and _is_field(right.args[0])
        ):
            # Handle special case: "key" in/not in dict(obj.field)
            # e.g. "foo" in dict(obj.field) -> {"obj.field.foo": {"$exists": True}}
            field_value = self.visit(right.args[0])
            if isinstance(left, ast.Constant) and isinstance(left.value, str):
                # Construct the dotted path for the nested field
                nested_field = f"{field_value}.{left.value}"
                exists_value = not is_not_in  # True for 'in', False for 'not in'
                return {nested_field: {"$exists": exists_value}}
            else:
                self._report_error(
                    node=node,
                    msg=f"For 'key {'not ' if is_not_in else ''}in dict(field)' pattern, key must be a string literal",
                    exception=QueryTranspilerValueError,
                )
        else:
            self._report_error(
                node=node,
                msg="An unexpected error occurred.",
                exception=QueryTranspilerError,
            )

    def _handle_comparison_operator(
        self, node: ast.Compare, left: ast.expr, op: ast.cmpop, right: ast.expr
    ) -> Dict[str, Any]:
        """Handle standard comparison operators (>, >=, <, <=, ==, !=)"""
        # Handle constant negative values without using $expr
        if _is_negative_constant(right) and _is_field(left):
            # For cases like a < -1, we can use a regular comparison without $expr
            return self._handle_standard_comparison(node, left, op, right)

        if _is_negative_constant(left) and _is_field(right):
            # For cases like -1 < a, we can use a swapped comparison without $expr
            return self._handle_swapped_comparison(node, left, op, right)

        # Check for complex expressions requiring $expr. E.g. foo > bar + 1
        # or negative field expressions like -foo < 0
        if isinstance(left, (ast.BinOp, ast.UnaryOp)) or isinstance(
            right, (ast.BinOp, ast.UnaryOp)
        ):
            return self._handle_expr_comparison(left, op, right)  # type: ignore

        # Handle field-to-field comparisons, e.g. foo > bar
        if _is_field(left) and _is_field(right):
            return self._handle_expr_comparison(left, op, right)

        # Handle cases where constant is on the left and field is on the right. E.g. {"foo": 0} == bar
        if _is_literal(left) and _is_field(right):
            return self._handle_swapped_comparison(node, left, op, right)

        # Handle regular comparisons between a field and a value
        return self._handle_standard_comparison(node, left, op, right)

    def _get_constant_value(self, node: ast.expr) -> Any:
        """Extract the value from a constant expression, handling negative constants specially"""
        if _is_negative_constant(node):
            # For negative constants like -1, directly compute the negative value
            return -self.visit(node.operand)  # type: ignore
        else:
            # Regular constant or other expression
            return self.visit(node)

    def _handle_field_value_comparison(
        self,
        node: ast.Compare,
        field_expr: ast.expr,
        op_type: type,
        value_expr: ast.expr,
    ) -> Dict[str, Any]:
        """Handle comparison between a field and a value with the given operator type"""
        field_name = self.visit(field_expr)
        value = self._get_constant_value(value_expr)

        if op_type == ast.Eq:
            # Simplify equality comparisons
            return {field_name: value}
        elif op_type in self.COMPARE_OP_MAP:
            mongo_op = self.COMPARE_OP_MAP[op_type]  # type: ignore
            return {field_name: {mongo_op: value}}
        else:
            self._report_error(
                node=node,
                msg=f"Unsupported comparison operator: {op_type}",
                exception=QueryTranspilerValueError,
            )

    def _handle_standard_comparison(
        self, node: ast.Compare, left: ast.expr, op: ast.cmpop, right: ast.expr
    ) -> Dict[str, Any]:
        """Handle regular comparisons between a field and a value"""
        return self._handle_field_value_comparison(node, left, type(op), right)

    def _handle_swapped_comparison(
        self, node: ast.Compare, left: ast.expr, op: ast.cmpop, right: ast.expr
    ) -> Dict[str, Any]:
        """Handle cases where constant is on left and field is on right (swapping them)"""
        op_type = type(op)
        if op_type not in self.INVERTED_OP_MAP:
            self._report_error(
                node=node,
                msg=f"Unsupported comparison operator: {op_type}",
                exception=QueryTranspilerValueError,
            )

        inverted_op_type = self.INVERTED_OP_MAP[op_type]  # type: ignore
        return self._handle_field_value_comparison(node, right, inverted_op_type, left)

    def _handle_expr_comparison(
        self, left: ast.expr, op: ast.cmpop, right: ast.expr
    ) -> Dict[str, Any]:
        """
        Handle complex comparisons that require MongoDB's $expr operator.
        Automatically adds existence checks for all fields referenced in the expression.

        Python: a + b > c, field1 > field2
        MongoDB: {
            "$and": [
                {"a": {"$exists": true}},
                {"b": {"$exists": true}},
                {"c": {"$exists": true}},
                {"$expr": {"$gt": [{"$add": ["$a", "$b"]}, "$c"]}}
            ]
        }

        This ensures that all fields referenced in the expression exist before
        evaluating the expression itself, preventing unexpected matching behavior
        when fields are missing. Such as foo >= bar yields True when none of 'foo' or 'bar' exists.
        """
        op_type = type(op)
        if op_type not in self.COMPARE_OP_MAP:
            raise QueryTranspilerValueError(
                f"Unsupported comparison operator in expression: {op_type}"
            )  # pragma: no cover

        mongo_op = self.COMPARE_OP_MAP[op_type]  # type: ignore
        left_expr = self._convert_to_expr(left)
        right_expr = self._convert_to_expr(right)

        # Collect all field references used in the expression
        field_exists_conditions = self._get_field_exists_conditions(left, right)

        # Create $expr with appropriate operator
        expr = {mongo_op: [left_expr, right_expr]}

        # If we have field existence checks, combine with $expr using $and
        if field_exists_conditions:
            return {"$and": [*field_exists_conditions, {"$expr": expr}]}
        else:
            return {"$expr": expr}

    def _get_field_exists_conditions(self, *nodes) -> List[Dict[str, Any]]:
        """
        Extract field names from AST nodes and create $exists conditions for them.
        This ensures fields referenced in $expr actually exist in documents.

        Returns:
            List of {field: {$exists: true}} conditions for all fields used
        """
        fields = set()

        def extract_fields(node):
            # Use our visitor method to get the full field path
            if _is_field(node):
                field_path = self.visit(node)
                fields.add(field_path)

            # Recursively process child nodes
            for child in ast.iter_child_nodes(node):
                extract_fields(child)

        for node in nodes:
            extract_fields(node)

        # Remove fields that are prefixes of longer fields
        # (i.e., if we check for "user.address.city", we don't need to check for "user" or "user.address")
        filtered_fields = set()
        for field in fields:
            if not any(
                other_field.startswith(field + ".")
                for other_field in fields
                if field != other_field
            ):
                filtered_fields.add(field)

        return [{field: {"$exists": True}} for field in filtered_fields]

    def _convert_to_expr(self, node: ast.AST) -> Any:
        """
        Convert an AST node to MongoDB $expr format
        Python: Various node types (field, constant, operation)
        MongoDB: "$field", value, or {$operation: [...]} formats
        """
        if _is_field(node):
            # Handle any type of field reference (Name, Attribute, Subscript)
            # Python: field, person.age, items[0], user['name']
            # MongoDB: "$field", "$person.age", "$items.0", "$user.name"
            field_path = self.visit(node)
            return f"${field_path}"
        elif isinstance(node, ast.Constant):
            # Keep literal values as they are
            # Python: 42, "text"
            # MongoDB: 42, "text"
            return node.value
        elif isinstance(node, ast.BinOp):
            # Handle binary operations in expressions
            # Python: a + b
            # MongoDB: {$add: ["$a", "$b"]}
            return self.visit_BinOp_expr(node)
        elif isinstance(node, ast.UnaryOp):
            # Handle unary operations in expressions
            # Python: -b
            # MongoDB: -value or {$multiply: [-1, "$b"]}
            if isinstance(node.op, ast.USub):  # Negative sign
                operand = self._convert_to_expr(node.operand)  # type: ignore
                if isinstance(
                    operand, (int, float)
                ):  # If constant, directly apply negative sign
                    return -operand
                # If field reference or other expression, use $multiply
                return {"$multiply": [-1, operand]}
            else:
                # Handle other unary operators or report error
                return self.visit(node)
        elif isinstance(node, ast.Call):
            # Process function calls in expressions
            # Python: function(args)
            # MongoDB: Result of the function call processor
            result = self.visit(node)
            return result
        else:
            # Handle other node types
            return self.visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> Dict[str, Any]:
        """
        Handle binary operations outside $expr context (not directly supported)
        Python: a + b (outside of comparison, which is prohibited)
        MongoDB: Error - binary operations must be in comparisons
        """
        self._report_error(
            node=node,
            msg="Binary operations like '+' or '-' must be used in comparisons for $expr. E.g. allowed: '1 + 1 > foo', disallowed: 1 + 1",
            exception=QueryTranspilerValueError,
        )

    def visit_BinOp_expr(self, node: ast.BinOp) -> Dict[str, Any]:
        """
        Process binary operations within $expr context
        Python: a + b, a - b, a * b, a / b, a % b
        MongoDB: {$add: ["$a", "$b"]}, {$subtract: ["$a", "$b"]}, etc.
        """
        left = self._convert_to_expr(node.left)  # type: ignore
        right = self._convert_to_expr(node.right)  # type: ignore

        # Map Python operators to MongoDB operators
        if isinstance(node.op, ast.Add):
            # Addition: a + b -> {$add: ["$a", "$b"]}
            return {"$add": [left, right]}
        elif isinstance(node.op, ast.Sub):
            # Subtraction: a - b -> {$subtract: ["$a", "$b"]}
            return {"$subtract": [left, right]}
        elif isinstance(node.op, ast.Mult):
            # Multiplication: a * b -> {$multiply: ["$a", "$b"]}
            return {"$multiply": [left, right]}
        elif isinstance(node.op, ast.Div):
            # Division: a / b -> {$divide: ["$a", "$b"]}
            return {"$divide": [left, right]}
        elif isinstance(node.op, ast.Mod):
            # Modulo: a % b -> {$mod: ["$a", "$b"]}
            return {"$mod": [left, right]}
        else:
            self._report_error(
                node=node,
                msg=f"Unsupported binary operator: {type(node.op)}",
                exception=QueryTranspilerValueError,
            )

    def visit_Name(self, node: ast.Name) -> str:
        """
        Process variable/field names
        Python: field_name
        MongoDB: "field_name" (as a field reference)
        """
        if self.allowed_fields and node.id not in self.allowed_fields:
            suggestions = difflib.get_close_matches(
                node.id, self.allowed_fields, n=1, cutoff=0.6
            )
            suggestion_msg = (
                f" Maybe you meant '{suggestions[0]}'?" if suggestions else ""
            )

            self._report_error(
                node=node,
                msg=f"Field '{node.id}' is unknown or not allowed.{suggestion_msg}"
                f"\nAllowed fields: {', '.join(sorted(self.allowed_fields))}",
                exception=QueryTranspilerValueError,
            )
        return node.id

    def visit_Attribute(self, node: ast.Attribute) -> str:
        """
        Process attribute access (dot notation)
        Python: person.address.city, inventory.items[0].price
        MongoDB: "person.address.city", "inventory.items.0.price" (as field references)
        """
        # Handle Name, Attribute, Subscript as valid base objects
        if isinstance(node.value, (ast.Name, ast.Attribute, ast.Subscript)):
            base = self.visit(node.value)
            return f"{base}.{node.attr}"
        else:  # could be Call, foo.bar().baz(), which is not supported
            self._report_error(
                node=node,
                msg=f"Unsupported attribute access: {ast.dump(node)}",
                exception=QueryTranspilerValueError,
            )

    def visit_Subscript(self, node: ast.Subscript) -> str:
        """
        Process subscript access (bracket notation)
        Python: person['address'], array[0]
        MongoDB: "person.address", "array.0" (as a field reference)

        Handles both old-style (Python 3.8-) and new-style (Python 3.9+) AST structures.
        """
        value = self.visit(node.value)  # Get the object being accessed

        # Python 3.8 and earlier uses an Index node
        if isinstance(node.slice, ast.Index):
            # Extract the value from the Index node
            if isinstance(node.slice.value, ast.Constant):  # type: ignore[attr-defined]
                index = node.slice.value.value  # type: ignore[attr-defined]
                # Type check: only allow string and integer subscripts
                if isinstance(index, (str, int)):
                    return f"{value}.{index}"
                else:
                    self._report_error(
                        # More specific node location
                        node=node.slice.value,  # type: ignore
                        msg=f"Only string and integer subscripts are supported, got: {type(index).__name__} with value {repr(index)}",
                        exception=QueryTranspilerValueError,
                    )
            # Handle negative indexing with unary operations
            elif isinstance(node.slice.value, ast.UnaryOp) and isinstance(  # type: ignore[attr-defined]
                node.slice.value.op, ast.USub  # type: ignore[attr-defined]
            ):
                # Get the operand value if possible
                operand_info = ""
                try:
                    if isinstance(node.slice.value.operand, ast.Constant):  # type: ignore[attr-defined]
                        operand_info = f" (value: -{node.slice.value.operand.value!s})"  # type: ignore[attr-defined]
                    elif isinstance(node.slice.value.operand, ast.Name):  # type: ignore[attr-defined]
                        operand_info = f" (variable: -{node.slice.value.operand.id})"  # type: ignore[attr-defined]
                except AttributeError:
                    pass

                self._report_error(
                    # More specific node location
                    node=node.slice.value,  # type: ignore
                    msg=f"Negative indexing is not supported{operand_info}",
                    exception=QueryTranspilerValueError,
                )
            else:
                self._report_error(
                    # More specific node location
                    node=node.slice.value,  # type: ignore
                    msg=f"Unsupported index value type: {type(node.slice.value).__name__}",  # type: ignore[attr-defined]
                    exception=QueryTranspilerValueError,
                )

        # Python 3.9+ directly uses the value
        elif isinstance(node.slice, ast.Constant):
            # Direct index or string key: foo[0] or foo['bar']
            index = node.slice.value

            # Type check: only allow string and integer subscripts
            if isinstance(index, (str, int)):
                return f"{value}.{index}"
            else:
                self._report_error(
                    # More specific node location
                    node=node.slice,  # type: ignore
                    msg=f"Only string and integer subscripts are supported, got: {type(index).__name__} with value {repr(index)}",
                    exception=QueryTranspilerValueError,
                )
        elif isinstance(node.slice, ast.UnaryOp) and isinstance(
            node.slice.op, ast.USub
        ):
            # Handle negative indexing in Python 3.9+ (like foo[-1])
            # Get the operand value if possible
            operand_info = ""
            try:
                if isinstance(node.slice.operand, ast.Constant):
                    operand_info = f" (value: -{node.slice.operand.value})"  # type: ignore[str-bytes-safe]
                elif isinstance(node.slice.operand, ast.Name):
                    operand_info = f" (variable: -{node.slice.operand.id})"
            except AttributeError:
                pass

            self._report_error(
                # More specific node location
                node=node.slice,  # type: ignore
                msg=f"Negative indexing is not supported{operand_info}",
                exception=QueryTranspilerValueError,
            )
        elif isinstance(node.slice, ast.Name):
            # Variable subscript access, not supported in MongoDB queries
            self._report_error(
                # More specific node location
                node=node.slice,  # type: ignore
                msg=f"Variable subscript is not supported in MongoDB queries: {node.slice.id}",
                exception=QueryTranspilerValueError,
            )
        else:
            self._report_error(
                # More specific node location
                node=node.slice,  # type: ignore
                msg=f"Unsupported subscript type: {type(node.slice).__name__}",
                exception=QueryTranspilerValueError,
            )

    def visit_Constant(self, node: ast.Constant) -> Any:
        """
        Process literal constants
        Python: 42, "text", True
        MongoDB: 42, "text", true
        """
        return node.value

    def visit_List(self, node: ast.List) -> List[Any]:
        """
        Process list literals
        Python: [1, 2, 3]
        MongoDB: [1, 2, 3]
        """
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> List[Any]:
        """
        Process tuple literals (converted to lists for MongoDB)
        Python: (1, 2, 3)
        MongoDB: [1, 2, 3]
        """
        return [self.visit(elt) for elt in node.elts]

    def visit_Dict(self, node):
        """
        Process dict literals (converted to dict for MongoDB)
        Python: {"foo": "bar"}
        MongoDB: {"foo": "bar"}
        """
        return {
            self.visit(key): self.visit(value)
            for key, value in zip(node.keys, node.values)
        }

    def visit_Call(self, node: ast.Call):
        """
        Process function calls
        Python: regex(field, pattern), exists(field), list(field), dict(field), etc.
        MongoDB: Various specialized query operators
        """
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        else:
            self._report_error(
                node=node,
                msg=f"Unsupported function call: {type(node.func)}",
                exception=QueryTranspilerValueError,
            )

        if func_name == "regex":
            # Regular expression matcher
            # Python: regex("name", "^Jo.*")
            # MongoDB: {"name": {"$regex": "^Jo.*"}}
            if len(node.args) != 2:
                self._report_error(
                    node=node,
                    msg="regex() requires two arguments: field name and pattern",
                    exception=QueryTranspilerValueError,
                )
            field = self.visit(node.args[0])
            pattern = self.visit(node.args[1])
            return {field: {"$regex": pattern}}

        elif func_name == "date":
            if len(node.args) != 1:
                self._report_error(
                    node=node,
                    msg="date('Y-M-D H:M:S') requires one argument: date string",
                    exception=QueryTranspilerValueError,
                )
            arg = self.visit(node.args[0])
            if not isinstance(arg, str):
                self._report_error(
                    node=node,
                    msg="date() argument must be a literal string, e.g. date('Y-M-D H:M:S') or date('7/25 23:33') or date('3 hours ago') etc.",
                    exception=QueryTranspilerValueError,
                )
            parsed_date = dateparser.parse(arg).astimezone(timezone.utc)
            if not parsed_date:
                self._report_error(
                    node=node,
                    msg="Invalid date string. Try using date('Y-M-D H:M:S') or date('7/25 23:33') or date('3 hours ago') etc.",
                    exception=QueryTranspilerValueError,
                )
            return parsed_date

        elif func_name == "exists":
            # Field existence check
            # Python: exists("optional_field"), exists("field", False)
            # MongoDB: {"optional_field": {"$exists": true}}, {"field": {"$exists": false}}
            if len(node.args) == 1:
                field = self.visit(node.args[0])
                return {field: {"$exists": True}}
            elif len(node.args) == 2:
                field = self.visit(node.args[0])
                exists = self.visit(node.args[1])
                return {field: {"$exists": exists}}
            else:
                self._report_error(
                    node=node,
                    msg='exists() requires one or two arguments: field name and optional boolean value. E.g. exists("optional_field"), exists("field", False)',
                    exception=QueryTranspilerValueError,
                )

        elif func_name == "list":
            # Handle list() conversion
            # When used outside of comparison context, we just pass through the field
            if len(node.args) != 1:
                self._report_error(
                    node=node,
                    msg="list() requires exactly one argument when used in queries",
                    exception=QueryTranspilerValueError,
                )
            # Just return the field value, since we're just indicating it's an array
            return self.visit(node.args[0])

        elif func_name == "dict":
            # Handle dict() conversion
            # When used outside of comparison context, we just pass through the field
            if len(node.args) != 1:
                self._report_error(
                    node=node,
                    msg="dict() requires exactly one argument when used in queries",
                    exception=QueryTranspilerValueError,
                )
            # Just return the field value, since we're just indicating it's a document
            return self.visit(node.args[0])

        self._report_error(
            node=node,
            msg=f"Unsupported function call: {func_name}",
            exception=QueryTranspilerValueError,
        )


def transpile_query(
    query_str: str, allowed_fields: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Transpile a Python-like query string and convert it to a MongoDB query object.

    Python: "age > 30 and (status == 'active' or role == 'admin')"
    MongoDB: {"$and": [{"age": {"$gt": 30}}, {"$or": [{"status": "active"}, {"role": "admin"}]}]}

    Args:
        query_str: A string containing a Python-like expression to be converted
        allowed_fields: A list of allowed fields (e.g. ast.Name.id). If None, allowed_fields will not be checked.

    Returns:
        A dictionary representing the equivalent MongoDB query

    Raises:
        QueryTranspilerValueError: If the query parsing fails
    """
    try:
        query_str = query_str.strip()
        parsed_ast = ast.parse(query_str)
        visitor = QueryTranspiler(query_str=query_str, allowed_fields=allowed_fields)
        result = visitor.visit(parsed_ast)

        if isinstance(result, bool) or isinstance(result, int):
            return {"$expr": True if result else False}

        if not isinstance(result, dict):
            raise QueryTranspilerValueError(
                f"Invalid query result: {result}. Query must evaluate to a dictionary."
            )

        return result

    except QueryTranspilerValueError as e:
        raise e.with_traceback(None)
    except SyntaxError as e:
        raise QueryTranspilerSyntaxError(f"Query syntax error: {str(e)}")
    except Exception as e:
        raise QueryTranspilerError(f"Query parsing failed: {str(e)}")
