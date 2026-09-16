"""Best-effort Worker presence, independent of all Task ownership traffic."""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from copy import deepcopy
from types import TracebackType

import httpx

from labtasker.client import REQUEST_TIMEOUT_SECONDS
from labtasker.config import ResolvedConfig
from labtasker.local import socket_transport
from labtasker.types import JSONValue
from labtasker.validation import validate_json_object

REPORT_INTERVAL_SECONDS = 60.0
SHUTDOWN_WAIT_SECONDS = 1.0
logger = logging.getLogger("labtasker.worker")


def _make_http_client(configuration: ResolvedConfig) -> httpx.Client:
    # This connection pool belongs exclusively to the reporter thread. No daemon
    # startup/recovery here: ordinary Worker preflight owns endpoint readiness.
    headers = (
        {} if configuration.token is None else {"Authorization": f"Bearer {configuration.token}"}
    )
    if configuration.local is not None:
        return httpx.Client(
            base_url="http://labtasker/api/v2/",
            headers=headers,
            transport=socket_transport(configuration.local),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    return httpx.Client(
        base_url=f"{configuration.url}/api/v2/", headers=headers, timeout=REQUEST_TIMEOUT_SECONDS
    )


class ObservationReporter:
    def __init__(
        self,
        configuration: ResolvedConfig,
        route: str,
        metadata: dict[str, JSONValue] | None = None,
    ) -> None:
        self.id = f"w_{secrets.token_urlsafe(9)}"
        self._configuration = configuration
        self._route = route
        self._metadata = deepcopy(
            validate_json_object({} if metadata is None else metadata, field="metadata")
        )
        self._pid = os.getpid()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._task_id: str | None = None
        self._closed = False
        self._deadline = 0.0
        self._thread = threading.Thread(
            target=self._run, name=f"labtasker-observation-{self.id}", daemon=True
        )
        self._started = False
        self._failing = False
        self._last_warning = float("-inf")

    def __enter__(self) -> ObservationReporter:
        try:
            self._thread.start()
            self._started = True
            self._wake.set()
        except Exception as error:
            self._failure(error)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if os.getpid() != self._pid:
            return
        # Called only after the loop has independently selected exit. Never
        # cancel a workload or change its outcome to meet this wait budget.
        try:
            with self._lock:
                self._closed = True
                self._deadline = time.monotonic() + SHUTDOWN_WAIT_SECONDS
            self._wake.set()
            if self._started:
                self._thread.join(max(0.0, self._deadline - time.monotonic()))
        except Exception as error:
            self._failure(error)

    def activity(self, task_id: str | None) -> None:
        if os.getpid() != self._pid:
            return
        with self._lock:
            if self._closed or self._task_id == task_id:
                return
            self._task_id = task_id
        self._wake.set()

    def _failure(self, error: Exception) -> None:
        now = time.monotonic()
        self._failing = True
        if now - self._last_warning >= REPORT_INTERVAL_SECONDS:
            self._last_warning = now
            logger.warning(
                "Worker observation unavailable (%s); Task execution is unaffected.",
                type(error).__name__,
            )

    def _run(self) -> None:
        client: httpx.Client | None = None
        path = f"queues/{self._configuration.queue}/workers/{self.id}"
        try:
            while True:
                self._wake.wait(REPORT_INTERVAL_SECONDS)
                self._wake.clear()
                with self._lock:
                    closed, deadline = self._closed, self._deadline
                if closed:
                    if client is not None and (remaining := deadline - time.monotonic()) > 0:
                        try:
                            response = client.delete(
                                path, timeout=min(remaining, REQUEST_TIMEOUT_SECONDS)
                            )
                            if response.status_code != 204:
                                response.raise_for_status()
                        except Exception as error:
                            self._failure(error)
                    return
                try:
                    if client is None:
                        client = _make_http_client(self._configuration)
                    # Transport initialization can outlive shutdown or an activity
                    # change. Re-read the latest state before starting any request.
                    with self._lock:
                        if self._closed:
                            continue
                        task_id = self._task_id
                    response = client.put(
                        path,
                        json={
                            "route": self._route,
                            "status": "idle" if task_id is None else "busy",
                            "task_id": task_id,
                            "metadata": self._metadata,
                        },
                    )
                    if response.status_code != 204:
                        response.raise_for_status()
                        raise ValueError("Unexpected observation response")
                except Exception as error:
                    self._failure(error)
                else:
                    if self._failing:
                        logger.info("Worker observation reporting recovered.")
                        self._failing = False
        except Exception as error:
            self._failure(error)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception as error:
                    self._failure(error)
