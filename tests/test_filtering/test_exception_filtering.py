import subprocess

import pytest

from tests.test_filtering.exception_utils import dummy_password


def run_fn_in_subprocess(package_name, fn_name):
    cmd = f"python -c 'import {package_name}; {package_name}.{fn_name}()'"
    result = subprocess.run(
        cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    return str(result.stdout) + str(result.stderr)


def placeholder(substituted: str) -> str:
    return "*" * len(substituted)


@pytest.mark.unit
class TestSanitizeSensitiveTraceback:
    """
    install_traceback_filter() is installed in labtasker.__init__.py
    """

    def test_raise_single_exception_no_protection(self):
        # test if hook disable is working
        output = run_fn_in_subprocess(
            "tests.test_filtering.exception_utils",
            "raise_single_exception_no_protection",
        )
        assert dummy_password in output  # since there is no protection

    def test_raise_single_exception(self):
        output = run_fn_in_subprocess(
            "tests.test_filtering.exception_utils", "raise_single_exception"
        )
        assert dummy_password not in output
        assert placeholder(dummy_password) in output

    def test_raise_chained_exception(self):
        output = run_fn_in_subprocess(
            "tests.test_filtering.exception_utils", "raise_chained_exception"
        )
        assert dummy_password not in output
        assert placeholder(dummy_password) in output

    def test_raise_with_decorator(self):
        output = run_fn_in_subprocess(
            "tests.test_filtering.exception_utils", "raise_with_decorator"
        )
        assert dummy_password not in output
        assert placeholder(dummy_password) in output

    def test_raise_with_ctx_manager(self):
        output = run_fn_in_subprocess(
            "tests.test_filtering.exception_utils", "raise_with_ctx_manager"
        )
        assert dummy_password not in output
        assert placeholder(dummy_password) in output

    def test_raise_fastapi_http_exception(self):
        output = run_fn_in_subprocess(
            "tests.test_filtering.exception_utils", "raise_fastapi_http_exception"
        )
        assert dummy_password not in output
        assert placeholder(dummy_password) in output
