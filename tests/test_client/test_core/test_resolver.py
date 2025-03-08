import inspect

import pytest
from typing_extensions import Annotated

from labtasker.client.core.exceptions import LabtaskerRuntimeError, LabtaskerValueError
from labtasker.client.core.resolver.models import Required
from labtasker.client.core.resolver.utils import (
    MixedAnnotatedAndDefaultStyleError,
    MultipleLabtaskerAnnotationsError,
    _split_annotation_from_labtasker_annotations,
    get_params_from_function,
    get_required_fields,
    resolve_args_partial,
)

pytestmark = [pytest.mark.unit]


class TestSplitAnnotationFromLabtaskerAnnotations:
    def test_non_annotated_type(self):
        annotation = str
        base_type, labtasker_annotations = _split_annotation_from_labtasker_annotations(
            annotation
        )
        assert base_type == str
        assert labtasker_annotations == []

    def test_annotated_with_non_parameter_info(self):
        annotation = Annotated[str, "metadata"]
        base_type, labtasker_annotations = _split_annotation_from_labtasker_annotations(
            annotation
        )
        assert base_type == str
        assert labtasker_annotations == []

    def test_annotated_with_parameter_info(self):
        req = Required()
        annotation = Annotated[str, req]
        base_type, labtasker_annotations = _split_annotation_from_labtasker_annotations(
            annotation
        )
        assert base_type == str
        assert labtasker_annotations == [req]

    def test_annotated_with_mixed_info(self):
        req = Required()
        annotation = Annotated[str, "metadata", req, 123]
        base_type, labtasker_annotations = _split_annotation_from_labtasker_annotations(
            annotation
        )
        assert base_type == str
        assert labtasker_annotations == [req]


class TestGetParamsFromFunction:
    def test_simple_function(self):
        def func(a: int, b: str):
            pass

        params = get_params_from_function(func)
        assert len(params) == 2
        assert params["a"].name == "a"
        assert params["a"].annotation == int
        assert params["a"].default is inspect.Parameter.empty
        assert params["b"].name == "b"
        assert params["b"].annotation == str
        assert params["b"].default is inspect.Parameter.empty

    def test_function_with_defaults(self):
        def func(a: int = 1, b: str = "default"):
            pass

        params = get_params_from_function(func)
        assert len(params) == 2
        assert params["a"].name == "a"
        assert params["a"].annotation == int
        assert params["a"].default == 1
        assert params["b"].name == "b"
        assert params["b"].annotation == str
        assert params["b"].default == "default"

    def test_function_with_required_annotation(self):
        def func(a: Annotated[int, Required()], b: str):
            pass

        params = get_params_from_function(func)
        assert len(params) == 2
        assert params["a"].name == "a"
        assert params["a"].annotation == int
        assert isinstance(params["a"].default, Required)
        assert params["a"].default.overwritten is False
        assert params["b"].name == "b"
        assert params["b"].annotation == str
        assert params["b"].default is inspect.Parameter.empty

    def test_function_with_required_annotation_and_default_value(self):
        def func(a: Annotated[int, Required()] = 10, b: str = "test"):
            pass

        params = get_params_from_function(func)
        assert len(params) == 2
        assert params["a"].name == "a"
        assert params["a"].annotation == int
        assert isinstance(params["a"].default, Required)
        assert params["a"].default.overwritten is True
        assert params["b"].name == "b"
        assert params["b"].annotation == str
        assert params["b"].default == "test"

    def test_multiple_annotations_error(self):
        def func(a: Annotated[int, Required(), Required()]):
            pass

        with pytest.raises(MultipleLabtaskerAnnotationsError) as excinfo:
            get_params_from_function(func)
        assert "a" in str(excinfo.value)

    def test_mixed_annotation_and_default_style_error(self):
        def func(a: Annotated[int, Required()] = Required()):
            pass

        with pytest.raises(MixedAnnotatedAndDefaultStyleError) as excinfo:
            get_params_from_function(func)
        assert "a" in str(excinfo.value)
        assert "Required" in str(excinfo.value)

    def test_required_as_default(self):
        def func(a: int = Required()):
            pass

        params = get_params_from_function(func)
        assert params["a"].default.overwritten is False
        assert params["a"].default.alias is None


class TestGetRequiredFields:
    def test_get_required_fields_simple(self):
        def func(a: Annotated[int, Required()], b: str = "default"):
            pass

        param_metas = get_params_from_function(func)
        required_fields = get_required_fields(param_metas)
        assert required_fields == ["a"]

    def test_get_required_fields_with_alias(self):
        def func(a: Annotated[int, Required(alias="foo.bar.a")], b: str = "default"):
            pass

        param_metas = get_params_from_function(func)
        required_fields = get_required_fields(param_metas)
        assert required_fields == ["foo.bar.a"]

    def test_get_required_fields_with_extra(self):
        def func(a: Annotated[int, Required()], b: str = "default"):
            pass

        param_metas = get_params_from_function(func)
        required_fields = get_required_fields(
            param_metas, extra_required_fields=["c.foo", "d"]
        )
        assert set(required_fields) == {"a", "c.foo", "d"}

    def test_get_required_fields_multiple_required(self):
        def func(
            a: Annotated[int, Required()],
            b: str = "default",
            c: Annotated[float, Required()] = None,
            d: Annotated[list, Required(alias="items")] = None,
        ):
            pass

        param_metas = get_params_from_function(func)
        required_fields = get_required_fields(param_metas)
        assert set(required_fields) == {"a", "c", "items"}

    def test_get_required_fields_no_required(self):
        def func(a: int = 1, b: str = "default"):
            pass

        param_metas = get_params_from_function(func)
        required_fields = get_required_fields(param_metas)
        assert required_fields == []


class TestResolveArgsPartial:
    def test_resolve_args_simple(self):
        def target_func(a: Annotated[int, Required()], b: str = "default"):
            return a, b

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        # first argument must be task args dict despite pass_args_dict=False
        # because we have altered the behaviour of target_func using resolve_args_partial
        result = wrapped({"a": 1}, b="test")
        assert result == (1, "test")

    def test_resolve_args_with_pass_args_dict(self):
        def target_func(task_args, a: Annotated[int, Required()], b: str = "default"):
            """The difference between pass_args_dict=True or False is whether target_func can directly access task_args
            as the first arg"""
            return task_args, a, b

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=True)
        task_args = {"a": 1}
        result = wrapped(task_args, b="test")
        assert result == (task_args, 1, "test")

    def test_resolve_args_with_type_caster(self):
        def type_caster(x):
            return int(x) * 2

        def target_func(
            a: Annotated[int, Required(resolver=type_caster)], b: str = "default"
        ):
            return a, b

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        result = wrapped({"a": "5"}, b="test")
        assert result == (10, "test")

    def test_resolve_args_with_alias(self):
        def target_func(
            a: Annotated[int, Required(alias="foo.bar.a")], b: str = "default"
        ):
            return a, b

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        # foo.bar.a are parsed as a structured field
        result = wrapped({"foo": {"bar": {"a": 1}}}, b="test")
        assert result == (1, "test")

    def test_resolve_args_positional_and_keyword(self):
        def target_func(
            a: Annotated[int, Required()], b: str, c: Annotated[float, Required()]
        ):
            return a, b, c

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        result = wrapped({"a": 1, "c": 3.14}, b="test")
        assert result == (1, "test", 3.14)

    def test_resolve_args_mixed_position_types(self):
        # Test different parameter kinds in the same function
        def target_func(
            a: Annotated[int, Required()],  # positional or keyword
            b: str,  # positional or keyword
            *args,  # var positional
            c: Annotated[float, Required()],  # keyword only
            **kwargs,  # var keyword
        ):
            return a, b, args, c, kwargs

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        result = wrapped(
            {"a": 1, "c": 3.14}, "hello", "extra1", "extra2", d="extra_kwarg"
        )
        assert result == (1, "hello", ("extra1", "extra2"), 3.14, {"d": "extra_kwarg"})

    def test_resolve_args_positional_only_with_default(self):
        def target_func(a: Annotated[int, Required()], /, b: str = "default"):
            return a, b

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        result = wrapped({"a": 1}, "test")
        assert result == (1, "test")

        with pytest.raises(LabtaskerValueError) as excinfo:
            wrapped({"a": 1}, a=5)
        assert "should be left blank and filled by labtasker" in str(excinfo.value)

    def test_resolve_extra_positional_args(self):
        def target_func(a: Annotated[int, Required()], b, c, d):
            return a, b, c, d

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        with pytest.raises(LabtaskerValueError, match="Got extra positional arguments"):
            wrapped({"a": 1}, 2, 3, 4, d=5)

    def test_resolve_extra_positional_args_only(self):
        def target_func(a: Annotated[int, Required()], b, c, d):
            return a, b, c, d

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        with pytest.raises(
            LabtaskerValueError, match="Too many positional arguments provided"
        ):
            wrapped({"a": 1}, 2, 3, 4, 5)

    def test_resolve_extra_keyword_args(self):
        def target_func(a: Annotated[int, Required()], b, c, d):
            return a, b, c, d

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)
        with pytest.raises(LabtaskerValueError, match="Unexpected keyword arguments"):
            wrapped({"a": 1}, 2, 3, d=5, f=6)

    def test_resolve_args_with_no_required(self):
        """Test resolve_args_partial with a function that has optional parameters but no required ones."""

        def target_func(a=10, b="default", c=None):
            return a, b, c

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)

        # Call with empty dict should use all defaults
        result = wrapped({})
        assert result == (10, "default", None)

        # Providing some parameters
        result = wrapped({"a": 20})
        assert result == (10, "default", None)

        # Test with keyword arguments that would override positional
        result = wrapped({"a": 60}, 70)
        assert result == (70, "default", None)  # Positional argument takes precedence

    def test_resolve_args_with_no_args(self):
        """Test resolve_args_partial with a function that takes no arguments."""

        def target_func():
            return "no args"

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)

        # Call with empty dict as args should work
        result = wrapped({})
        assert result == "no args"

        # Call with no args would raise a TypeError says missing 1 required positional argument: 'task_args'
        with pytest.raises(
            TypeError, match="missing 1 required positional argument: 'task_args'"
        ):
            wrapped()

        # Extra args should be ignored
        result = wrapped({"extra": "arg"})
        assert result == "no args"

    def test_resolve_args_with_no_args_and_pass_args_dict(self):
        """Test resolve_args_partial with pass_args_dict=True and a function that takes no arguments."""

        def target_func():
            return "no args"

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=True)

        # Call with empty dict as args
        with pytest.raises(
            LabtaskerValueError,
            match="Too many positional arguments provided.",
        ):
            wrapped({})

        # Test with a function that accepts the args_dict
        def target_func_with_args(args_dict=None):
            return f"args: {args_dict}"

        param_metas = get_params_from_function(target_func_with_args)
        wrapped = resolve_args_partial(
            target_func_with_args, param_metas, pass_args_dict=True
        )

        # Now the extra args should be accessible
        result = wrapped({"extra": "arg"})
        assert result == "args: {'extra': 'arg'}"

    def test_error_when_required_field_missing_from_task_args(self):
        def target_func(a: Annotated[int, Required()], b: str = "default"):
            return a, b

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)

        with pytest.raises(LabtaskerRuntimeError) as excinfo:
            wrapped({}, b="test")  # Missing required 'a'
        assert "Required field 'a' not found in task args" in str(excinfo.value)

    def test_error_when_type_casting_fails(self):
        def type_caster(x):
            return int(x)  # Will fail if x is not convertible to int

        def target_func(
            a: Annotated[int, Required(resolver=type_caster)], b: str = "default"
        ):
            return a, b

        param_metas = get_params_from_function(target_func)
        wrapped = resolve_args_partial(target_func, param_metas, pass_args_dict=False)

        with pytest.raises(LabtaskerRuntimeError) as excinfo:
            wrapped({"a": "not_an_int"}, b="test")
        assert "Failed to process field 'a' with type caster" in str(excinfo.value)
