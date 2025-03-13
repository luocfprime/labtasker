# Partially adapted from https://github.com/fastapi/typer/blob/d2504fb15ac88aecdc3a88d2fad3b422f9a36f8d/typer/utils.py#L107

import inspect
import sys
from copy import copy
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Type

from typing_extensions import Annotated, get_args, get_origin, get_type_hints

from labtasker.client.core.exceptions import (
    LabtaskerError,
    LabtaskerRuntimeError,
    LabtaskerValueError,
)
from labtasker.client.core.resolver.models import ParameterInfo, ParamMeta, Required


def _param_type_to_user_string(param_type: Type[ParameterInfo]) -> str:
    # Render a `ParameterInfo` subclass for use in error messages.
    # User code doesn't call `*Info` directly, so errors should present the classes how
    # they were (probably) defined in the user code.
    if param_type is Required:
        return "`Required`"
    # This line shouldn't be reachable during normal use.
    return f"`{param_type.__name__}`"  # pragma: no cover


class MultipleLabtaskerAnnotationsError(LabtaskerError):
    argument_name: str

    def __init__(self, argument_name: str):
        self.argument_name = argument_name

    def __str__(self) -> str:
        return (
            "Cannot specify multiple `Annotated` Labtasker arguments"
            f" for {self.argument_name!r}"
        )


class MixedAnnotatedAndDefaultStyleError(LabtaskerError):
    argument_name: str
    annotated_param_type: Type[ParameterInfo]
    default_param_type: Type[ParameterInfo]

    def __init__(
        self,
        argument_name: str,
        annotated_param_type: Type[ParameterInfo],
        default_param_type: Type[ParameterInfo],
    ):
        self.argument_name = argument_name
        self.annotated_param_type = annotated_param_type
        self.default_param_type = default_param_type

    def __str__(self) -> str:
        annotated_param_type_str = _param_type_to_user_string(self.annotated_param_type)
        default_param_type_str = _param_type_to_user_string(self.default_param_type)
        msg = f"Cannot specify {annotated_param_type_str} in `Annotated` and"
        if self.annotated_param_type is self.default_param_type:
            msg += " default value"
        else:
            msg += f" {default_param_type_str} as a default value"
        msg += f" together for {self.argument_name!r}"
        return msg


def _split_annotation_from_labtasker_annotations(
    base_annotation: Type[Any],
) -> Tuple[Type[Any], List[ParameterInfo]]:
    if get_origin(base_annotation) is not Annotated:
        return base_annotation, []
    base_annotation, *maybe_labtasker_annotations = get_args(base_annotation)
    return base_annotation, [
        annotation
        for annotation in maybe_labtasker_annotations
        if isinstance(annotation, ParameterInfo)
    ]


def get_params_from_function(func: Callable[..., Any]) -> Dict[str, ParamMeta]:
    if sys.version_info >= (3, 10):
        signature = inspect.signature(func, eval_str=True)  # noqa
    else:
        signature = inspect.signature(func)

    type_hints = get_type_hints(func)
    params = {}
    for param in signature.parameters.values():
        annotation, labtasker_annotations = (
            _split_annotation_from_labtasker_annotations(
                param.annotation,
            )
        )
        if len(labtasker_annotations) > 1:
            raise MultipleLabtaskerAnnotationsError(param.name)

        default = param.default
        if labtasker_annotations:
            # It's something like `my_param: Annotated[str, Required()]`
            [parameter_info] = labtasker_annotations

            # Forbid `my_param: Annotated[str, Required()] = Required("...")`
            if isinstance(param.default, ParameterInfo):
                raise MixedAnnotatedAndDefaultStyleError(
                    argument_name=param.name,
                    annotated_param_type=type(parameter_info),
                    default_param_type=type(param.default),
                )

            parameter_info = copy(parameter_info)

            if param.default is not param.empty:
                # Since the default value is not empty and will be overwritten by Labtasker
                parameter_info.overwritten = True

            default = parameter_info
        elif param.name in type_hints:
            # Resolve forward references.
            annotation = type_hints[param.name]

        params[param.name] = ParamMeta(
            name=param.name,
            kind=param.kind,
            default=default,
            annotation=annotation,
        )
    return params


def get_required_fields(
    param_metas: Dict[str, ParamMeta],
    extra_required_fields: Optional[List[str]] = None,
) -> List[str]:
    """
    Get required fields from function ParamMeta
    Args:
        param_metas:
        extra_required_fields:

    Returns: required_fields as a tree structured dict

    """
    required_fields: Set[str] = set()
    for meta in param_metas.values():
        if isinstance(meta.default, Required):
            if meta.default.alias:
                # use alias as required field
                required_fields.add(meta.default.alias)
            else:
                required_fields.add(meta.name)

    if extra_required_fields:
        extra_required_fields = set(extra_required_fields)  # type: ignore[assignment]

        # merge required_fields together
        required_fields = required_fields | extra_required_fields  # type: ignore[operator]

    return list(required_fields)


def get_nested_value(data, path):
    """Retrieve a value from nested dictionary structure.
    Works with both direct keys and dot-notation paths.

    Args:
        data: The dictionary to search in
        path: A string path (can be a simple key or dot-separated path)

    Returns:
        The value at the specified path

    Raises:
        KeyError: If the path doesn't exist in the data
    """
    # First try direct access (handles both simple keys and
    # cases where the exact key with dots exists)
    if path in data:
        return data[path]

    # Try as a dot-separated path
    parts = path.split(".")
    current = data

    try:
        for part in parts:
            current = current[part]
        return current
    except (KeyError, TypeError):
        # If we can't traverse the path or the structure isn't as expected
        raise KeyError(f"Cannot find path '{path}' in data")


def resolve_args_partial(
    func, /, param_metas: Dict[str, ParamMeta], pass_args_dict: bool
):
    """
    Process function parameter injection, supporting automatic filling of parameters annotated with Required

    Args:
        func: Original function
        param_metas: Dictionary of parameter metadata
        pass_args_dict: Whether to pass task_args as the first positional argument
    """
    # Collect all params marked with Required(...)
    required_params = {}
    for name, param_meta in param_metas.items():
        if isinstance(param_meta.default, Required):
            required_params[name] = param_meta.default

    @wraps(func)
    def wrapped(task_args, /, *job_fn_args, **job_fn_kwargs):
        # 1. Preprocess task_args and extract required values
        injected_values = {}

        for name, req in required_params.items():
            field_name = req.alias or name
            type_caster = req.resolver or (lambda x: x)

            try:
                value = get_nested_value(task_args, field_name)
                injected_values[name] = type_caster(value)
            except KeyError as e:
                raise LabtaskerRuntimeError(
                    f"Required field {name!r} not found in task args"
                ) from e
            except Exception as e:
                raise LabtaskerRuntimeError(
                    f"Failed to process field {name!r} with type caster"
                ) from e

        # 2. Prepare arguments
        args = []
        kwargs = {}

        # If task_args should be passed as the first parameter
        if pass_args_dict:
            job_fn_args = [task_args] + list(job_fn_args)

        # Check for conflicts between injected parameters and user-provided parameters
        conflicts = set(injected_values) & set(job_fn_kwargs)
        if conflicts:
            conflicting = next(iter(conflicts))
            raise LabtaskerValueError(
                f"Field {conflicting} should be left blank and filled by labtasker. "
                f"Yet you provided it as keyword argument with value: {job_fn_kwargs[conflicting]}"
            )

        # 3. Build parameter list in order
        available_positionals = list(job_fn_args)  # Copy because we'll modify it

        for name, param_meta in param_metas.items():
            # Determine if this parameter should be passed as positional or keyword argument
            # Handle special parameter types
            if param_meta.kind == inspect.Parameter.VAR_POSITIONAL:
                args.extend(available_positionals)
                available_positionals = []
                continue
            elif param_meta.kind == inspect.Parameter.VAR_KEYWORD:
                # Handle **kwargs parameter: add remaining user-provided keyword arguments to kwargs
                for k, v in job_fn_kwargs.items():
                    if k not in kwargs:
                        kwargs[k] = v
                continue

            # Determine the value for this parameter
            if name in job_fn_kwargs:
                # User provided this parameter as a keyword argument
                kwargs[name] = job_fn_kwargs[name]
                # Once we have a keyword argument, subsequent regular parameters must also be passed as keywords
                if available_positionals:
                    raise LabtaskerValueError(
                        f"Got extra positional arguments {available_positionals} after a keyword argument: {name}={kwargs[name]}"
                    )
            elif name in injected_values:
                # This is a parameter that needs to be injected
                if not available_positionals or param_meta.kind in (
                    inspect.Parameter.KEYWORD_ONLY,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    # If no positional arguments are available or the parameter is keyword-only, add as keyword
                    kwargs[name] = injected_values[name]
                else:
                    # Otherwise add as positional argument
                    args.append(injected_values[name])
            elif available_positionals:
                # Use a user-provided positional argument
                args.append(available_positionals.pop(0))
            elif param_meta.default is not inspect.Parameter.empty:
                # Use default value
                continue  # No need to explicitly add, Python will handle it automatically
            else:
                # No value available
                raise LabtaskerRuntimeError(
                    f"Required parameter {name!r} not provided and not injected"
                )

        # Check if there are unused positional arguments
        if available_positionals:
            raise LabtaskerValueError(
                f"Too many positional arguments provided. "
                f"Filled: {args}, remaining: {available_positionals}"
            )

        # Check if there are unused keyword arguments
        used_kwargs = set(kwargs.keys())
        unused_kwargs = set(job_fn_kwargs.keys()) - used_kwargs
        if unused_kwargs and not any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in param_metas.values()
        ):
            raise LabtaskerValueError(f"Unexpected keyword arguments: {unused_kwargs}")

        return func(*args, **kwargs)

    return wrapped
