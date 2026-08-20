"""Compile the command Worker's intentionally small interpolation language.

Grammar::

    path       = segment ("." segment)*
    segment    = start continue*
    start      = ASCII letter | "_"
    continue   = start | ASCII digit

In text, ``%{{`` emits a literal ``%{`` and ``%{path}`` emits a path piece.
Every scanner transition advances the Unicode input by at least one code point.
The language is regular and fail-fast; it has no nesting or error recovery.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from labtasker.paths import PathError, select_path
from labtasker.types import JSONValue


class TemplateSyntaxError(ValueError):
    def __init__(self, message: str, *, element: int, column: int) -> None:
        self.element = element
        self.column = column
        super().__init__(f"argv element {element}, column {column}: {message}")


class TemplateBindingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _PathPiece:
    segments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CompiledTemplate:
    pieces: tuple[str | _PathPiece, ...]

    def resolve(self, args: dict[str, JSONValue]) -> str:
        rendered: list[str] = []
        for piece in self.pieces:
            if isinstance(piece, str):
                rendered.append(piece)
                continue
            try:
                selected = select_path(args, piece.segments)
            except PathError as error:
                raise TemplateBindingError(str(error)) from error
            rendered.append(_render_value(selected))
        value = "".join(rendered)
        if "\0" in value:
            raise TemplateBindingError("resolved argv element contains NUL")
        return value


def compile_argv(argv: list[str]) -> tuple[CompiledTemplate, ...]:
    if not argv:
        raise ValueError("command must contain at least one argv element")
    return tuple(_compile_element(value, element=index) for index, value in enumerate(argv, 1))


def resolve_argv(
    templates: tuple[CompiledTemplate, ...],
    args: dict[str, JSONValue],
) -> list[str]:
    return [template.resolve(args) for template in templates]


def _compile_element(value: str, *, element: int) -> CompiledTemplate:
    pieces: list[str | _PathPiece] = []
    literal: list[str] = []
    index = 0
    while index < len(value):
        previous = index
        if value.startswith("%{{", index):
            literal.append("%{")
            index += 3
        elif value.startswith("%{", index):
            if literal:
                pieces.append("".join(literal))
                literal.clear()
            opening = index
            index += 2
            segments, index = _scan_path(value, index, element=element, opening=opening)
            pieces.append(_PathPiece(segments))
        else:
            if value[index] == "\0":
                raise TemplateSyntaxError(
                    "literal argv text contains NUL",
                    element=element,
                    column=index + 1,
                )
            literal.append(value[index])
            index += 1
        if index <= previous:  # pragma: no cover - implementation invariant
            raise AssertionError("command template scanner did not advance")
    if literal or not pieces:
        pieces.append("".join(literal))
    return CompiledTemplate(tuple(pieces))


def _scan_path(
    value: str,
    index: int,
    *,
    element: int,
    opening: int,
) -> tuple[tuple[str, ...], int]:
    segments: list[str] = []
    current: list[str] = []
    expecting_start = True
    while index < len(value):
        character = value[index]
        if character == "}":
            if expecting_start:
                raise TemplateSyntaxError(
                    "placeholder has an empty path segment",
                    element=element,
                    column=index + 1,
                )
            segments.append("".join(current))
            return tuple(segments), index + 1
        if expecting_start:
            if _is_start(character):
                current.append(character)
                expecting_start = False
                index += 1
                continue
        elif character == ".":
            segments.append("".join(current))
            current.clear()
            expecting_start = True
            index += 1
            continue
        elif _is_continue(character):
            current.append(character)
            index += 1
            continue
        raise TemplateSyntaxError(
            f"invalid placeholder character {character!r}",
            element=element,
            column=index + 1,
        )
    raise TemplateSyntaxError(
        "unterminated placeholder",
        element=element,
        column=opening + 1,
    )


def _is_start(character: str) -> bool:
    return character == "_" or "A" <= character <= "Z" or "a" <= character <= "z"


def _is_continue(character: str) -> bool:
    return _is_start(character) or "0" <= character <= "9"


def _render_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
