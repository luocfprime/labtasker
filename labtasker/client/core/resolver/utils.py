# Partially adapted from https://github.com/fastapi/typer/blob/d2504fb15ac88aecdc3a88d2fad3b422f9a36f8d/typer/utils.py#L107

import inspect
import sys
from copy import copy
from functools import wraps
from typing import Any, Callable, Dict, List, Set, Tuple, Type, Union

from typing_extensions import Annotated, get_args, get_origin, get_type_hints

from labtasker.client.core.exceptions import (
    LabtaskerError,
    LabtaskerRuntimeError,
    LabtaskerValueError,
)
from labtasker.client.core.resolver.models import ParameterInfo, ParamMeta, Required
from labtasker.utils import flatten_dict


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
            default=default,  # type: Union[ParameterInfo, Any]
            annotation=annotation,
        )
    return params


def get_required_fields(
    param_metas: Dict[str, ParamMeta] = None,
    extra_required_fields: List[str] = None,
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
        extra_required_fields = set(extra_required_fields)

        # merge required_fields together
        required_fields = required_fields | extra_required_fields

    return list(required_fields)


def resolve_args_partial(
    func, /, param_metas: Dict[str, ParamMeta], pass_args_dict: bool
):
    """
    Takes in task_args, apply custom type_caster if available, fill in the args and kwargs for the required fields, and return the wrapped function
    Args:
        func:
        param_metas:
        pass_args_dict: Whether to pass the fetched task args dict as the first positional argument of the job function

    Returns:

    """

    required = {
        param_meta.name: param_meta.default
        for param_meta in param_metas.values()
        if isinstance(param_meta.default, Required)
    }

    type_casters = {}
    for name, r in required.items():
        field_name = r.alias or name
        if r.type_caster is not None:
            type_casters[name] = (field_name, r.type_caster)
        else:
            type_casters[name] = (field_name, lambda x: x)  # identity function

    @wraps(func)
    def wrapped(task_args, /, *job_fn_args, **job_fn_kwargs):
        """
        1. Use type_casters to convert sub-fields of task_args to the required types
        2. Construct the positional and keyword arguments that should be passed into the func

        Args:
            task_args:
            *job_fn_args:
            **job_fn_kwargs:

        Returns:

        """
        task_args_flattened = flatten_dict(task_args)
        # 1. resolve args and kwargs
        resolved_args = {}
        for name, (field_name, caster) in type_casters.items():
            try:
                resolved_args[name] = caster(task_args_flattened[field_name])
            except KeyError as e:
                raise LabtaskerRuntimeError(
                    f"Required field {name!r} is not found in task args"
                ) from e
            except Exception as e:
                raise LabtaskerRuntimeError(
                    f"Failed to resolve field {name!r} with type caster {caster!r}"
                ) from e

        # 2. construct the partial function

        # Scan left to right along each parameter to determine whether to fill in as positional or keyword arguments
        how_to_fill = {}

        kwargs_only = False  # scan left to right, after the first keyword argument, no positional arguments should follow
        for param_meta in param_metas.values():
            name = param_meta.name

            if name in job_fn_kwargs:
                # if it is provided as a keyword argument, it should be filled in as a keyword argument
                # and every parameter after it should be filled in as a keyword argument
                if param_meta.kind == inspect.Parameter.POSITIONAL_ONLY:
                    raise LabtaskerRuntimeError(
                        f"Required field {name!r} got some positional-only arguments passed as keyword arguments."
                    )
                kwargs_only = True
                how_to_fill[name] = "keyword"
                continue

            if (
                param_meta.kind == inspect.Parameter.POSITIONAL_ONLY
                or param_meta.kind == inspect.Parameter.VAR_POSITIONAL
            ):
                how_to_fill[param_meta.name] = "positional"
                if kwargs_only:
                    raise LabtaskerRuntimeError(
                        f"Required field {name!r} positional argument follows a keyword argument."
                    )
            elif param_meta.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
                # prioritize positional argument over keyword argument to allow more flexibility
                how_to_fill[name] = "keyword" if kwargs_only else "positional"
            elif (
                param_meta.kind == inspect.Parameter.KEYWORD_ONLY
                or param_meta.kind == inspect.Parameter.VAR_KEYWORD
            ):
                how_to_fill[name] = "keyword"
                kwargs_only = True
            else:  # pragma: no cover
                raise LabtaskerRuntimeError(
                    f"Unknown parameter kind {param_meta.kind!r} for field {name!r}"
                )

        # Fill in the args and kwargs
        job_fn_args_idx = 0  # a pointer to the job_fn_args
        args = [task_args] if pass_args_dict else []
        kwargs = {}

        def _get_arg(name):
            # check for conflict
            if name in job_fn_kwargs and name in resolved_args:
                raise LabtaskerValueError(
                    f"Field {name} should be left blank and filled by labtasker, because you have specified it via Required(...). "
                    f"Yet you have provided with keyword argument with value {name}={job_fn_kwargs[name]}."
                )

            if name in job_fn_kwargs:
                return job_fn_kwargs[name]
            elif name in resolved_args:
                return resolved_args[name]
            else:
                raise LabtaskerRuntimeError(
                    f"Field {name!r} is not filled in by labtasker and you have not specified it via keyword argument."
                )

        for name, how in how_to_fill.items():
            if how == "positional":
                if name in resolved_args:
                    args.append(resolved_args[name])
                else:
                    # not specified by Required(...), use the next user provided positional argument
                    if job_fn_args_idx >= len(job_fn_args):
                        raise LabtaskerRuntimeError(
                            f"Required field {name!r} is not filled in by labtasker and you have not specified it via positional argument.\n"
                            f"You may have provided less args than required.\n"
                            f"Context: currently filled args: {args}, user provided positional args: {job_fn_args}"
                        )
                    args.append(job_fn_args[job_fn_args_idx])
                    job_fn_args_idx += 1
            elif how == "keyword":
                kwargs[name] = _get_arg(name)
            else:  # pragma: no cover
                raise LabtaskerRuntimeError(
                    f"Unknown how to fill {name!r} with value {how!r}"
                )

        return func(*args, **kwargs)

    return wrapped
