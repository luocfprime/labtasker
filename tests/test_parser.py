from shlex import split

import pytest

from labtasker.client.core.cmd_parser import cmd_interpolate
from labtasker.utils import keys_to_query_dict


@pytest.fixture
def params():
    return {
        "arg1": "value1",
        "arg2": {"arg3": "value3", "arg4": {"arg5": "value5", "arg6": [0, 1, 2]}},
    }


@pytest.mark.unit
class TestParseCmd:

    def test_basic(self, params):
        cmd = "python main.py --arg1 {{arg1}} --arg2 {{arg2}}"
        parsed, _ = cmd_interpolate(cmd, params)

        tgt_cmd = r'python main.py --arg1 value1 --arg2 {"arg3": "value3", "arg4": {"arg5": "value5", "arg6": [0, 1, 2]}}'
        assert split(parsed) == split(tgt_cmd), f"got {parsed}"

    def test_keys_to_query_dict(self, params):
        cmd = "python main.py --arg1 {{arg1}} --arg2 {{arg2.arg4.arg5}}"
        parsed, keys = cmd_interpolate(cmd, params)
        query_dict = keys_to_query_dict(list(keys))

        tgt_cmd = r"python main.py --arg1 value1 --arg2 value5"
        tgt_query_dict = {"arg1": None, "arg2": {"arg4": {"arg5": None}}}

        assert split(parsed) == split(tgt_cmd), f"got {parsed}"
        assert query_dict == tgt_query_dict, f"got {query_dict}"
