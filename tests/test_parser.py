import os
import shlex
import sys
from io import StringIO
from typing import List

import pytest

from labtasker.client.core.cmd_parser import cmd_interpolate
from labtasker.client.core.exceptions import CmdParserError
from labtasker.utils import keys_to_query_dict


@pytest.fixture(autouse=True)
def test_suppress_stderr():
    """Suppress the stderr produced by parser format print."""
    original_stderr = sys.stderr
    sys.stderr = StringIO()
    try:
        yield
    finally:
        sys.stderr = original_stderr


@pytest.fixture
def params():
    return {
        "arg1": "value1",
        "arg2": {"arg3": "value3", "arg4": {"arg5": "value5", "arg6": [0, 1, 2]}},
    }


def _split(cmd: str) -> List[str]:
    return shlex.split(cmd, posix=os.name == "posix")


@pytest.mark.unit
class TestParseCmd:
    def test_basic(self, params):
        cmd = _split("python main.py --arg1 %(arg1) --arg2 %(arg2)")
        parsed, _ = cmd_interpolate(cmd, params)

        tgt_cmd = [
            "python",
            "main.py",
            "--arg1",
            "value1",
            "--arg2",
            '{"arg3": "value3", "arg4": {"arg5": "value5", "arg6": [0, 1, 2]}}',
        ]
        assert parsed == tgt_cmd, f"expected {tgt_cmd}, got {parsed}"
        assert len(parsed) == 6, f"got {len(parsed)}"

    def test_basic_list(self, params):
        cmd = _split("python main.py --arg1 %(arg1) --arg2 %(arg2)")
        parsed, _ = cmd_interpolate(cmd, params)

        tgt_cmd = [
            "python",
            "main.py",
            "--arg1",
            "value1",
            "--arg2",
            '{"arg3": "value3", "arg4": {"arg5": "value5", "arg6": [0, 1, 2]}}',
        ]
        assert len(parsed) == 6, f"got {len(parsed)}"
        assert parsed == tgt_cmd, f"expected {tgt_cmd}, got {parsed}"

    def test_keys_to_query_dict(self, params):
        cmd = _split("python main.py --arg1 %(arg1) --arg2 %(arg2.arg4.arg5)")
        parsed, keys = cmd_interpolate(cmd, params)
        query_dict = keys_to_query_dict(list(keys))

        tgt_cmd = _split("python main.py --arg1 value1 --arg2 value5")
        tgt_query_dict = {"arg1": None, "arg2": {"arg4": {"arg5": None}}}

        assert parsed == tgt_cmd, f"got {parsed}"
        assert query_dict == tgt_query_dict, f"got {query_dict}"

    def test_missing_key(self, params):
        cmd = _split("python main.py --arg1 %()")
        with pytest.raises(CmdParserError):
            cmd_interpolate(cmd, params)

    def test_no_exist_key(self, params):
        cmd = _split("python main.py --arg1 %(arg_non_existent)")
        with pytest.raises(KeyError):
            cmd_interpolate(cmd, params)

    def test_unmatch_parentheses(self, params):
        cmd = _split("python main.py --arg1 %(( arg1 )")
        with pytest.raises(CmdParserError):
            cmd_interpolate(cmd, params)

        cmd = _split("python main.py --arg1 %(arg1")
        with pytest.raises(CmdParserError):
            cmd_interpolate(cmd, params)

        cmd = _split("python main.py --arg1 ( %(arg1)")
        parsed, _ = cmd_interpolate(cmd, params)
        assert parsed == _split("python main.py --arg1 ( value1"), f"got {parsed}"

        # Note: --arg1 %(arg1)) is allowed for now.
        # Since the extra ')' is considered as new part of cmd string.
        # which give us "--arg1 value1)"

    def test_empty_command(self, params):
        cmd = _split("")
        parsed, _ = cmd_interpolate(cmd, params)
        assert parsed == [], "Command should remain empty"

        parsed, _ = cmd_interpolate([], params)
        assert parsed == [], "Command should remain empty"

    def test_empty_params(self):
        cmd = _split("python main.py --arg1 %(arg1)")
        params = {}
        with pytest.raises(KeyError):
            cmd_interpolate(cmd, params)

    def test_only_template(self, params):
        cmd = _split("%(arg1)")
        parsed, _ = cmd_interpolate(cmd, params)
        assert parsed == ["value1"], f"got {parsed}"

    def test_special_characters(self, params):
        cmd = _split("python main.py $abc $@ $* $ $? $# --arg1 %(arg1)")
        parsed, _ = cmd_interpolate(cmd, params)

        assert parsed == _split(
            "python main.py $abc $@ $* $ $? $# --arg1 value1"
        ), f"got {parsed}"

    def test_int_index_as_key(self):
        """Test interpolation like %(1) %(2), useful when using interpolating positional arguments such as in `python main.py --foo %(foo) %(1) %(2)`"""
        params = {"1": "positional_1", "foo": {"bar": "hello"}}
        cmd = _split("python main.py --foo.bar %(foo.bar) %(1)")
        parsed, _ = cmd_interpolate(cmd, params)
        assert parsed == _split(
            "python main.py --foo.bar hello positional_1"
        ), f"got {parsed}"
