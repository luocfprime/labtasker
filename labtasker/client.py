import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv


class Task:
    """Represents a task with status tracking and reporting capabilities."""

    def __init__(self, client: "Tasker", task_data: Dict[str, Any]):
        self.client = client
        self.task_id = task_data.get("task_id")
        self.args = task_data.get("args", {})
        self.metadata = task_data.get("metadata", {})
        self.status = task_data.get("status")

    def report(self, status: str, summary: Optional[Dict[str, Any]] = None) -> None:
        """Report task status and summary."""
        url = f"{self.client.server_address}/api/v1/queues/{self.client.queue_name}/tasks/{self.task_id}"
        data = {
            "status": status,
            "summary": summary or {},
        }
        try:
            response = requests.patch(url, json=data)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Failed to report task status: {str(e)}")


class Tasker:
    def __init__(self, client_config: str):
        """Initialize Tasker client with configuration file."""
        if not os.path.exists(client_config):
            raise FileNotFoundError(f"Config file not found: {client_config}")

        load_dotenv(client_config)

        self.server_address = os.getenv("HTTP_SERVER_ADDRESS")
        self.queue_name = os.getenv("QUEUE_NAME")
        self.password = os.getenv("PASSWORD")

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

    def _start_heartbeat(self, task_id: str) -> threading.Thread:
        """Start heartbeat thread for a task."""

        def heartbeat():
            url = f"{self.server_address}/api/v1/queues/{self.queue_name}/tasks/{task_id}/heartbeat"
            while True:
                try:
                    response = requests.post(url)
                    response.raise_for_status()
                    time.sleep(30)  # Send heartbeat every 30 seconds
                except:
                    break

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        return thread

    def fetch(
        self, eta_max: str = "2h", start_heartbeat: bool = False
    ) -> Dict[str, Any]:
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
                self._start_heartbeat(task.task_id)
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

    def get_tasks(
        self,
        queue_id: Optional[str] = None,
        queue_name: Optional[str] = None,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        status: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get list of tasks from a queue."""
        params = {"password": self.password}
        if queue_id:
            params["queue_id"] = queue_id
        if queue_name:
            params["queue_name"] = queue_name
        if task_id:
            params["task_id"] = task_id
        if task_name:
            params["task_name"] = task_name
        if status:
            params["status"] = status
        if tag:
            params["tag"] = tag

        response = self._get("/api/v1/tasks", params=params)
        return response.json()["tasks"]
