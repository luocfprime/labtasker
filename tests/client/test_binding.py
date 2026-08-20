from __future__ import annotations

from typing import Any

import pytest

from labtasker.binding import BindingError, TaskArg, compile_binding


def test_named_binding_ignores_extra_args_and_keeps_startup_values() -> None:
    observed: list[tuple[object, ...]] = []

    def handler(
        model: object,
        prompt: str = TaskArg(),
        steps: int = TaskArg(default=30),
        **kwargs: object,
    ) -> None:
        observed.append((model, prompt, steps, kwargs))

    binding = compile_binding(handler)
    binding.validate_invocation(("loaded",), {"fixed": True})
    binding.invoke(
        {"prompt": "cat", "unused": 9},
        ("loaded",),
        {"fixed": True},
    )
    assert observed == [("loaded", "cat", 30, {"fixed": True})]


def test_nested_path_resolver_and_strict_annotation() -> None:
    def handler(
        learning_rate: float = TaskArg(
            path="optimizer.lr",
            resolver=lambda value: float(value),
        ),
    ) -> float:
        return learning_rate

    binding = compile_binding(handler)
    assert binding.invoke({"optimizer": {"lr": "0.01"}}, (), {}) == 0.01

    def strict(count: int = TaskArg()) -> int:
        return count

    strict_binding = compile_binding(strict)
    assert strict_binding.invoke({"count": 2}, (), {}) == 2
    for invalid in (2.0, "2", True):
        with pytest.raises(BindingError, match="strict validation"):
            strict_binding.invoke({"count": invalid}, (), {})  # type: ignore[dict-item]


def test_missing_default_and_unannotated_values_share_pipeline() -> None:
    def handler(
        required=TaskArg(),
        optional: str | None = TaskArg(default=None),
    ) -> tuple[Any, str | None]:
        return required, optional

    binding = compile_binding(handler)
    assert binding.invoke({"required": [1, 2]}, (), {}) == ([1, 2], None)
    with pytest.raises(BindingError, match="missing key 'required'"):
        binding.invoke({}, (), {})


def test_value_dependent_resolver_failure_is_binding_error() -> None:
    def resolver(_: object) -> int:
        raise LookupError("unsupported")

    def handler(value: int = TaskArg(resolver=resolver)) -> None:
        pass

    with pytest.raises(BindingError, match="resolver failed: unsupported"):
        compile_binding(handler).invoke({"value": 1}, (), {})


@pytest.mark.parametrize(
    "handler",
    [
        lambda value=TaskArg(path="bad-key"): None,
        lambda value=TaskArg(resolver="not-callable"): None,
        lambda value=TaskArg(resolver=lambda: None): None,
        lambda value=TaskArg(resolver=lambda first, second: None): None,
    ],
)
def test_invalid_static_markers_fail_during_compilation(handler: Any) -> None:
    with pytest.raises(TypeError):
        compile_binding(handler)


def test_async_handler_and_resolver_are_rejected() -> None:
    async def async_handler() -> None:
        pass

    async def async_resolver(value: object) -> object:
        return value

    with pytest.raises(TypeError, match="synchronous"):
        compile_binding(async_handler)

    def handler(value: object = TaskArg(resolver=async_resolver)) -> None:
        pass

    with pytest.raises(TypeError, match="synchronous"):
        compile_binding(handler)


def test_startup_cannot_override_injected_parameter() -> None:
    def handler(fixed: str, prompt: str = TaskArg()) -> None:
        pass

    binding = compile_binding(handler)
    with pytest.raises(TypeError, match="cannot be passed: prompt"):
        binding.validate_invocation(("fixed",), {"prompt": "wrong"})


def test_taskarg_typing_facade_returns_runtime_marker() -> None:
    marker: int = TaskArg(default=3)
    assert marker != 3
