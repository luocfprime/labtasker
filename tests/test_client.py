import os
import tempfile
import unittest

import responses

from labtasker import LabtaskerClient


class TestTasker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up mock server responses"""
        cls.responses = responses.RequestsMock()
        cls.responses.start()

        # Success responses
        cls.responses.add(
            responses.POST,
            "http://localhost:8080/api/v1/queues",
            json={"status": "success", "queue_id": "test_id"},
            status=200,
        )

        cls.responses.add(
            responses.POST,
            "http://localhost:8080/api/v1/queues/test_queue/tasks",
            json={"status": "success", "task_id": "test_task_id"},
            status=200,
        )

        cls.responses.add(
            responses.GET,
            "http://localhost:8080/api/v1/queues/test_queue/tasks",
            json={
                "status": "success",
                "task_id": "test_task_id",
                "args": {},
                "metadata": {},
            },
            status=200,
        )

        # Add mock for fetch task
        cls.responses.add(
            responses.GET,
            "http://localhost:8080/api/v1/tasks/next",
            json={
                "status": "success",
                "task_id": "test_task_id",
                "args": {"param1": 1},
                "metadata": {"tags": ["test_tag"]},
            },
            status=200,
        )

        # Add mock for submit task
        cls.responses.add(
            responses.POST,
            "http://localhost:8080/api/v1/tasks",
            json={"status": "success", "task_id": "test_task_id"},
            status=200,
        )

    @classmethod
    def tearDownClass(cls):
        cls.responses.stop(allow_assert=False)
        cls.responses.reset()

    def setUp(self):
        # Create a temporary config file for testing
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, "test_config.env")

        with open(self.config_path, "w") as f:
            f.write(
                """
HTTP_SERVER_ADDRESS=localhost:8080
QUEUE_NAME=test_queue
PASSWORD=test_password
"""
            )

    def tearDown(self):
        # Clean up temporary files
        os.remove(self.config_path)
        os.rmdir(self.temp_dir)

    def test_init_with_valid_config(self):
        tasker = LabtaskerClient(self.config_path)
        self.assertEqual(tasker.server_address, "http://localhost:8080")
        self.assertEqual(tasker.queue_name, "test_queue")
        self.assertEqual(tasker.password, "test_password")

    def test_init_with_invalid_config(self):
        with self.assertRaises(FileNotFoundError):
            LabtaskerClient("nonexistent_config.env")

    def test_create_queue(self):
        tasker = LabtaskerClient(self.config_path)
        status, queue_id = tasker.create_queue()
        self.assertEqual(status, "success")
        self.assertEqual(queue_id, "test_id")

    def test_submit_task(self):
        tasker = LabtaskerClient(self.config_path)
        status, task_id = tasker.submit(
            task_name="test_task",
            args={"param1": 1, "param2": 2},
            metadata={"tag": "test"},
        )
        self.assertEqual(status, "success")
        self.assertEqual(task_id, "test_task_id")

    def test_fetch_task(self):
        tasker = LabtaskerClient(self.config_path)
        task = tasker.fetch(eta_max="2h")
        self.assertIsNotNone(task)
        self.assertEqual(task.task_id, "test_task_id")

    def test_error_responses(self):
        # Add error response for testing
        self.responses.reset()
        self.responses.add(
            responses.POST,
            "http://localhost:8080/api/v1/queues",
            json={"status": "error", "message": "Queue already exists"},
            status=409,
        )

        tasker = LabtaskerClient(self.config_path)
        status, message = tasker.create_queue()
        self.assertEqual(status, "error")
        self.assertIn("Queue already exists", message)

        # Restore success responses for other tests
        self.setUpClass()

    def test_ls_tasks(self):
        """Test getting task list."""
        # Setup mock response
        self.responses.add(
            responses.GET,
            "http://localhost:8080/api/v1/tasks",
            json={
                "status": "success",
                "tasks": [
                    {
                        "_id": "task1",
                        "task_name": "test_task",
                        "status": "created",
                        "args": {"param1": 1},
                        "metadata": {"tags": ["test_tag"]},
                    }
                ],
            },
            status=200,
        )

        # Test getting tasks with different filters
        tasker = LabtaskerClient(self.config_path)
        tasks = tasker.ls_tasks(task_name="test_task", status="created")
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["_id"], "task1")
        self.assertEqual(tasks[0]["task_name"], "test_task")


if __name__ == "__main__":
    unittest.main()
