import json
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


class Task:
    """Represents a task with status tracking and reporting capabilities."""

    def __init__(self, client: "LabtaskerClient", task_data: Dict[str, Any]):
        self.client = client
        self.task_id = task_data.get("task_id")
        self.args = task_data.get("args", {})
        self.metadata = task_data.get("metadata", {})
        self.status = task_data.get("status")
        self._heartbeat_thread = None
        self._stop_heartbeat = threading.Event()

    def report(self, status: str, summary: Optional[Dict[str, Any]] = None) -> None:
        """Report task status and summary."""
        url = f"{self.client.server_address}/api/v1/queues/{self.client.queue_name}/tasks/{self.task_id}"  # noqa: E501
        data = {
            "status": status,
            "summary": summary or {},
        }
        try:
            response = requests.patch(url, json=data)
            response.raise_for_status()
            if status in ["completed", "failed"]:
                self.stop_heartbeat()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to report task status: {str(e)}")

    def start_heartbeat(self, interval: int = 30):
        """Start the heartbeat thread."""

        def heartbeat():
            url = f"{self.client.server_address}/api/v1/queues/{self.client.queue_name}/tasks/{self.task_id}/heartbeat"  # noqa: E501
            while not self._stop_heartbeat.is_set():
                try:
                    response = requests.post(url)
                    response.raise_for_status()
                    self._stop_heartbeat.wait(interval)
                except Exception as e:
                    print(f"Heartbeat failed: {e}")
                    continue

        self._heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        self._heartbeat_thread.start()

    def stop_heartbeat(self):
        """Stop the heartbeat thread."""
        if self._heartbeat_thread:
            self._stop_heartbeat.set()
            self._heartbeat_thread.join(timeout=1)
            self._heartbeat_thread = None


class LabtaskerClient:
    def __init__(
        self,
        client_config: str = os.path.join(os.getcwd(), ".labtasker", "client.env"),
    ):
        """Initialize LabtaskerClient client with configuration file."""
        if not os.path.exists(client_config):
            raise FileNotFoundError(f"Config file not found: {client_config}")

        load_dotenv(client_config)

        self.server_address = os.getenv("HTTP_SERVER_ADDRESS")
        self.queue_name = os.getenv("QUEUE_NAME")
        self.password = os.getenv("PASSWORD")
        self.heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", 10))

        if not all([self.server_address, self.queue_name, self.password]):
            raise ValueError("Missing required configuration values")

        # Ensure server address has proper format
        if not self.server_address.startswith(("http://", "https://")):
            self.server_address = f"http://{self.server_address}"

    def create_queue(self) -> Tuple[str, Optional[str]]:
        """Create a new task queue."""
        url = f"{self.server_address}/api/v1/queues"
        data = {"queue_name": self.queue_name, "password": self.password}

        try:
            response = requests.post(url, json=data)
            result = response.json()
            if response.status_code >= 400:
                return "error", result.get("message", "Unknown error")
            return "success", result.get("queue_id")
        except requests.exceptions.RequestException as e:
            return "error", str(e)

    def submit(
        self, task_name: str, args: Dict[str, Any], metadata: Dict[str, Any] = None
    ) -> Tuple[str, Optional[str]]:
        """Submit a task to the queue."""
        url = f"{self.server_address}/api/v1/queues/{self.queue_name}/tasks"
        data = {
            "queue_name": self.queue_name,
            "password": self.password,
            "task_name": task_name,
            "args": args,
            "metadata": metadata or {},
        }

        try:
            response = requests.post(url, json=data)
            result = response.json()
            if response.status_code >= 400:
                return "error", result.get("message", "Unknown error")
            return "success", result.get("task_id")
        except requests.exceptions.RequestException as e:
            return "error", str(e)

    def fetch(
        self, eta_max: str = "2h", start_heartbeat: bool = False
    ) -> Optional[Task]:
        """Fetch a task from the queue."""
        url = f"{self.server_address}/api/v1/tasks/next"
        params = {
            "password": self.password,
            "queue_name": self.queue_name,
            "eta_max": eta_max,
            "start_heartbeat": start_heartbeat,
        }

        try:
            response = requests.get(url, params=params)
            result = response.json()
            if response.status_code >= 400:
                return None
            if result["status"] == "no_task":
                return None

            task = Task(self, result)
            if start_heartbeat:
                task.start_heartbeat(interval=self.heartbeat_interval)
            return task

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to fetch task: {str(e)}")

    def _get(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        """Make a GET request to the server."""
        url = f"{self.server_address}{path}"
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Request failed: {str(e)}")

    def ls_tasks(
        self,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        status: Optional[str] = None,
        extra_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get list of tasks from a queue."""
        if extra_filter:
            try:
                extra_filter = json.loads(extra_filter)
            except json.JSONDecodeError:
                raise ValueError("Invalid extra_filter format")

        params = {
            "password": self.password,
            **{
                k: v
                for k, v in {
                    "queue_name": self.queue_name,
                    "task_id": task_id,
                    "task_name": task_name,
                    "status": status,
                    "extra_filter": extra_filter,
                }.items()
                if v is not None
            },
        }

        response = self._get("/api/v1/tasks", params=params)
        return response.json()["tasks"]
