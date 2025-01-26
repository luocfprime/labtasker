# import json
# import os
# import tempfile
# import unittest
#
# import responses
# from click.testing import CliRunner
#
# from labtasker.client.cli import cli
#
#
# class TestCLI(unittest.TestCase):
#     @classmethod
#     def setUpClass(cls):
#         cls.responses = responses.RequestsMock(assert_all_requests_are_fired=False)
#         cls.responses.start()
#
#     @classmethod
#     def tearDownClass(cls):
#         cls.responses.stop()
#
#     def setUp(self):
#         self.runner = CliRunner()
#         self.temp_dir = tempfile.mkdtemp()
#         self.config_path = os.path.join(self.temp_dir, "test_config.env")
#
#         with open(self.config_path, "w") as f:
#             f.write(
#                 """
# HTTP_SERVER_ADDRESS=localhost:8080
# QUEUE_NAME=test_queue
# PASSWORD=test_password
# """
#             )
#
#     def tearDown(self):
#         os.remove(self.config_path)
#         os.rmdir(self.temp_dir)
#
#     def test_config_command(self):
#         result = self.runner.invoke(
#             cli, ["config", "--client-config", self.config_path]
#         )
#         self.assertEqual(result.exit_code, 0)
#         self.assertIn("Configuration validated successfully!", result.output)
#
#     def test_create_queue_command(self):
#         result = self.runner.invoke(
#             cli, ["create-queue", "--client-config", self.config_path]
#         )
#         self.assertEqual(result.exit_code, 0)
#         # Since we're not running a real server, we expect an error message
#         self.assertIn("Error", result.output)
#
#     def test_submit_command(self):
#         args = json.dumps({"param1": 1, "param2": 2})
#         metadata = json.dumps({"tag": "test"})
#
#         result = self.runner.invoke(
#             cli,
#             [
#                 "submit",
#                 "--client-config",
#                 self.config_path,
#                 "--task-name",
#                 "test_task",
#                 "--args",
#                 args,
#                 "--metadata",
#                 metadata,
#             ],
#         )
#
#         self.assertEqual(result.exit_code, 0)
#         # Since we're not running a real server, we expect an error message
#         self.assertIn("Error", result.output)
#
#     def test_ls_tasks(self):
#         """Test ls-tasks command with various filters."""
#         # Mock the HTTP request
#         self.responses.add(
#             responses.GET,
#             "http://localhost:8080/api/v1/tasks",
#             json={
#                 "status": "success",
#                 "tasks": [
#                     {
#                         "task_id": "test_task_id",
#                         "task_name": "test_task",
#                         "status": "created",
#                         "args": {"param1": 1},
#                         "metadata": {"tags": ["test_tag"]},
#                     }
#                 ],
#             },
#             status=200,
#         )
#
#         # Test basic ls-tasks with queue id
#         result = self.runner.invoke(
#             cli,
#             ["ls-tasks", "--client-config", self.config_path],
#         )
#         assert result.exit_code == 0
#         assert "test_task_id" in result.output
#         assert "test_task" in result.output
#
#         # Test with filters
#         result = self.runner.invoke(
#             cli,
#             [
#                 "ls-tasks",
#                 "--client-config",
#                 self.config_path,
#                 "--status",
#                 "created",
#             ],
#         )
#         assert result.exit_code == 0
#         assert "created" in result.output
#
#         # Test ls-tasks command with various filters.
#         # Reset responses
#         self.responses.reset()
#
#         expected_task = {
#             "task_id": "test_task_id",
#             "task_name": "test_task",
#             "status": "created",
#             "args": {"param1": 1},
#             "metadata": {"tags": ["test_tag"]},
#         }
#
#         self.responses.add(
#             responses.GET,
#             "http://localhost:8080/api/v1/tasks",
#             json={"status": "success", "tasks": [expected_task]},
#             match=[
#                 responses.matchers.query_param_matcher(
#                     {
#                         "queue_name": "test_queue",
#                         "password": "test_password",
#                         "task_name": "test_task",
#                     }
#                 )
#             ],
#             status=200,
#         )
#
#         result = self.runner.invoke(
#             cli,
#             [
#                 "ls-tasks",
#                 "--client-config",
#                 self.config_path,
#                 "--task-name",
#                 "test_task",
#             ],
#         )
#         assert result.exit_code == 0, f"Error output: {result.output}"
#         output = json.loads(result.output)
#         assert len(output) == 1
#         assert output[0] == expected_task
#
#
# if __name__ == "__main__":
#     unittest.main()
