from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, get_type_hints, overload

from pydantic import TypeAdapter, ValidationError

from labtasker.paths import PathError, parse_path, select_path
from labtasker.types import JSONValue

T = TypeVar("T")
_MISSING = object()


@dataclass(frozen=True, slots=True)
class _TaskArgMarker:
    default: object
    path: str | None
    resolver: Callable[[Any], Any] | None


@overload
def TaskArg(
    *,
    default: T,
    path: str | None = None,
    resolver: None = None,
) -> T: ...


@overload
def TaskArg(
    *,
    default: object = _MISSING,
    path: str | None = None,
    resolver: Callable[[Any], T],
) -> T: ...


@overload
def TaskArg(
    *,
    default: object = _MISSING,
    path: str | None = None,
    resolver: None = None,
) -> Any: ...


def TaskArg(
    *,
    default: object = _MISSING,
    path: str | None = None,
    resolver: Callable[[Any], Any] | None = None,
) -> Any:
    """Mark one decorated Worker parameter as coming from Task args."""
    return _TaskArgMarker(default=default, path=path, resolver=resolver)


class BindingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _Injection:
    name: str
    path: tuple[str, ...]
    default: object
    resolver: Callable[[Any], Any] | None
    adapter: TypeAdapter[Any] | None

    def resolve(self, args: dict[str, JSONValue]) -> Any:
        try:
            value = select_path(args, self.path)
        except PathError as error:
            if self.default is _MISSING:
                raise BindingError(f"TaskArg {self.name!r}: {error}") from error
            value = self.default
        if self.resolver is not None:
            try:
                value = self.resolver(value)
            except Exception as error:
                raise BindingError(f"TaskArg {self.name!r} resolver failed: {error}") from error
        if self.adapter is not None:
            try:
                value = self.adapter.validate_python(value, strict=True)
            except ValidationError as error:
                message = f"TaskArg {self.name!r} failed strict validation: {error}"
                raise BindingError(message) from error
        return value


@dataclass(frozen=True, slots=True)
class CompiledBinding:
    function: Callable[..., Any]
    signature: inspect.Signature
    injections: tuple[_Injection, ...]

    def validate_invocation(self, args: tuple[object, ...], kwargs: dict[str, object]) -> None:
        bound = self.signature.bind(*args, **kwargs)
        supplied = {injection.name for injection in self.injections} & bound.arguments.keys()
        if supplied:
            names = ", ".join(sorted(supplied))
            raise TypeError(
                f"TaskArg parameters are supplied by Labtasker and cannot be passed: {names}"
            )

    def invoke(
        self,
        task_args: dict[str, JSONValue],
        startup_args: tuple[object, ...],
        startup_kwargs: dict[str, object],
    ) -> Any:
        bound = self.signature.bind(*startup_args, **startup_kwargs)
        for injection in self.injections:
            bound.arguments[injection.name] = injection.resolve(task_args)
        return self.function(*bound.args, **bound.kwargs)


def compile_binding(function: Callable[..., Any]) -> CompiledBinding:
    if _is_async_callable(function):
        raise TypeError("Labtasker v2 Worker handlers must be synchronous functions.")
    signature = inspect.signature(function)
    try:
        hints = get_type_hints(function, include_extras=True)
    except Exception as error:
        raise TypeError(f"Could not resolve Worker annotations: {error}") from error
    injections: list[_Injection] = []
    for parameter in signature.parameters.values():
        marker = parameter.default
        if not isinstance(marker, _TaskArgMarker):
            continue
        if parameter.kind in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            raise TypeError(f"TaskArg parameter {parameter.name!r} must accept a keyword value.")
        if marker.path is not None and not isinstance(marker.path, str):
            raise TypeError(f"TaskArg path for {parameter.name!r} must be a string or None.")
        try:
            path = parse_path(parameter.name if marker.path is None else marker.path)
        except PathError as error:
            raise TypeError(f"Invalid TaskArg path for {parameter.name!r}: {error}") from error
        resolver = marker.resolver
        if resolver is not None:
            _validate_resolver(resolver, parameter.name)
        annotation = hints.get(parameter.name, parameter.annotation)
        adapter: TypeAdapter[Any] | None = None
        if annotation is not inspect.Parameter.empty:
            try:
                adapter = TypeAdapter(annotation)
            except Exception as error:
                raise TypeError(
                    f"Could not compile annotation for TaskArg {parameter.name!r}: {error}"
                ) from error
        injections.append(
            _Injection(
                name=parameter.name,
                path=path,
                default=marker.default,
                resolver=resolver,
                adapter=adapter,
            )
        )
    return CompiledBinding(function=function, signature=signature, injections=tuple(injections))


def _validate_resolver(resolver: object, name: str) -> None:
    if not callable(resolver):
        raise TypeError(f"TaskArg resolver for {name!r} must be callable.")
    if _is_async_callable(resolver):
        raise TypeError(f"TaskArg resolver for {name!r} must be synchronous.")
    try:
        signature = inspect.signature(resolver)
    except (TypeError, ValueError) as error:
        raise TypeError(f"Could not inspect TaskArg resolver for {name!r}.") from error
    parameters = list(signature.parameters.values())
    if len(parameters) != 1 or parameters[0].kind not in {
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    }:
        raise TypeError(f"TaskArg resolver for {name!r} must accept exactly one value.")


def _is_async_callable(value: object) -> bool:
    return inspect.iscoroutinefunction(value) or inspect.iscoroutinefunction(type(value).__call__)
