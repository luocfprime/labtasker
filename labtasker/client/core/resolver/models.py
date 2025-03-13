# Partially adapted from https://github.com/fastapi/typer/blob/d2504fb15ac88aecdc3a88d2fad3b422f9a36f8d/typer/models.py#L508
import inspect
from typing import Any, Callable, Optional


class ParameterInfo:
    def __init__(self):
        self.overwritten = False  # Whether default value is overwritten by labtasker. Used to trigger a warning.


class Required(ParameterInfo):
    def __init__(
        self,
        *,
        alias: Optional[str] = None,
        resolver: Optional[Callable[[Any], Any]] = None,
    ):
        super().__init__()
        self.alias = alias
        self.resolver = resolver


class ParamMeta:
    empty = inspect.Parameter.empty

    def __init__(
        self,
        *,
        name: str,
        kind: inspect.Parameter.kind,  # type: ignore[valid-type]
        default: Any = inspect.Parameter.empty,
        annotation: Any = inspect.Parameter.empty,
    ) -> None:
        self.name = name
        self.kind = kind
        self.default = default
        self.annotation = annotation
