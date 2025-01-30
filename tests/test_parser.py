# import pytest
#
# from labtasker.client.core.parser import parse_cmd
#
#
# @pytest.fixture
# def params():
#     return {
#         "arg1": "value1",
#         "arg2": {"arg3": "value3", "arg4": {"arg5": "value5", "arg6": [0, 1, 2]}},
#     }
#
#
# @pytest.mark.unit
# class TestParseCmd:
#
#     def test_basic(self, params):
#         cmd = "python main.py --arg1 {{arg1}} --arg2 {{arg2}}"
#         parsed = parse_cmd(cmd, params)
#         assert (
#             parsed
#             == r'python main.py --arg1 value1 --arg2 {"arg3": "value3", "arg4": {"arg5": "value5", "arg6": [0, 1, 2]}}'
#         ), f"got {parsed}"
#
#     def test_nested(self, params):
#         cmd = "python main.py --arg1 {{arg1}} --arg2 {{arg2.arg3}}"
