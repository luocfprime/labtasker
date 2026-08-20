from __future__ import annotations

import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from labtasker.command_template import (
    TemplateBindingError,
    TemplateSyntaxError,
    compile_argv,
    resolve_argv,
)


@pytest.mark.parametrize(
    ("template", "expected"),
    [
        ("%", "%"),
        ("%%", "%%"),
        ("%{a}", "x"),
        ("%{{a}", "%{a}"),
        ("%%{a}", "%x"),
        ("%%%{a}", "%%x"),
        ("%{a}%{b}", "xy"),
        ("}", "}"),
        ("before-%{a}-after", "before-x-after"),
    ],
)
def test_scanner_golden_cases(template: str, expected: str) -> None:
    assert resolve_argv(compile_argv([template]), {"a": "x", "b": "y"}) == [expected]


def test_resolution_preserves_one_element_and_uses_canonical_json() -> None:
    templates = compile_argv(["", "%{text}", "x%{config}y", "%{flag}", "%{nothing}"])
    assert resolve_argv(
        templates,
        {
            "text": "hello world",
            "config": {"z": [1, 2], "a": "模型"},
            "flag": True,
            "nothing": None,
        },
    ) == ["", "hello world", 'x{"a":"模型","z":[1,2]}y', "true", "null"]


@pytest.mark.parametrize(
    ("template", "column"),
    [
        ("%{}", 3),
        ("%{.a}", 3),
        ("%{a.}", 5),
        ("%{a..b}", 5),
        ("%{a-b}", 4),
        ("%{模型}", 3),
        ("%{a", 1),
    ],
)
def test_invalid_paths_have_exact_location(template: str, column: int) -> None:
    with pytest.raises(TemplateSyntaxError) as raised:
        compile_argv(["ok", template])
    assert raised.value.element == 2
    assert raised.value.column == column
    assert str(raised.value).startswith(f"argv element 2, column {column}:")


def test_binding_errors_do_not_start_from_static_syntax() -> None:
    template = compile_argv(["%{optimizer.lr}"])
    with pytest.raises(TemplateBindingError, match="missing key 'lr'"):
        resolve_argv(template, {"optimizer": {}})
    with pytest.raises(TemplateBindingError, match="non-object"):
        resolve_argv(template, {"optimizer": 2})
    with pytest.raises(TemplateBindingError, match="NUL"):
        resolve_argv(compile_argv(["%{value}"]), {"value": "a\0b"})
    with pytest.raises(TemplateSyntaxError, match="literal argv text contains NUL"):
        compile_argv(["a\0b"])


def test_empty_command_is_rejected_but_empty_element_is_valid() -> None:
    with pytest.raises(ValueError, match="at least one"):
        compile_argv([])
    assert resolve_argv(compile_argv([""]), {}) == [""]


_START = string.ascii_letters + "_"
_CONTINUE = _START + string.digits
_SEGMENT = st.text(_CONTINUE, min_size=0, max_size=10).flatmap(
    lambda suffix: st.sampled_from(_START).map(lambda first: first + suffix)
)
_PATH = st.lists(_SEGMENT, min_size=1, max_size=5).map(".".join)


@given(_PATH)
def test_generated_valid_paths_compile(path: str) -> None:
    compiled = compile_argv([f"left%{{{path}}}right"])
    current: dict[str, object] = {}
    root = current
    segments = path.split(".")
    for segment in segments[:-1]:
        child: dict[str, object] = {}
        current[segment] = child
        current = child
    current[segments[-1]] = "value"
    assert resolve_argv(compiled, root) == ["leftvalueright"]


@given(st.text(max_size=300))
def test_arbitrary_unicode_always_terminates_with_success_or_located_error(value: str) -> None:
    try:
        compile_argv([value])
    except TemplateSyntaxError as error:
        assert error.element == 1
        assert 1 <= error.column <= len(value) + 1
