"""
Client-side event handling for Labtasker.
Provides APIs for subscribing to and processing server-sent events.
"""

import json
import threading
import time
from queue import Empty, Queue
from typing import Iterator, Optional

import httpx
import stamina
from httpx_sse import ServerSentEvent, connect_sse

from labtasker.api_models import EventResponse
from labtasker.client.core.api import get_httpx_client
from labtasker.client.core.config import get_client_config
from labtasker.client.core.exceptions import LabtaskerRuntimeError
from labtasker.client.core.logging import logger
from labtasker.security import get_auth_headers


class EventListener:
    """Client-side event listener for Labtasker server events."""

    def __init__(self):
        """
        Initialize an event listener.
        """
        self.config = get_client_config()
        self.base_url = self.config.endpoint.api_base_url
        self.auth_headers = get_auth_headers(
            self.config.queue.queue_name, self.config.queue.password
        )

        self._event_queue: Queue = Queue()
        self._stop_event = threading.Event()
        self._listener_thread: Optional[threading.Thread] = None
        self._client_id: Optional[str] = None
        self._connected = False
        self._error: Optional[Exception] = None

        self._retry_context_iter = None
        self.retry_context_iter(reset=True)

    def start(self, timeout: int = 10) -> "EventListener":
        """
        Start listening for events.

        Args:
            timeout: Maximum time to wait for connection in seconds.

        Returns:
            Self for method chaining.

        Raises:
            LabtaskerRuntimeError: If connection fails within the timeout period.
        """
        if self._listener_thread and self._listener_thread.is_alive():
            return self

        self._stop_event.clear()
        self._error = None
        self._connected = False

        # Start the listener thread
        self._listener_thread = threading.Thread(
            target=self._event_listener_thread, daemon=True
        )
        self._listener_thread.start()

        # Wait for connection or error
        start_time = time.time()
        while not self._connected and not self._error:
            if time.time() - start_time > timeout:
                self.stop()
                raise LabtaskerRuntimeError("Timeout waiting for event connection")
            time.sleep(0.1)

        if self._error:
            self.stop()
            if isinstance(self._error, httpx.HTTPError):
                raise self._error  # let httpx error propagate
            raise LabtaskerRuntimeError(
                f"Failed to connect to event stream: {self._error}"
            )

        return self

    def stop(self) -> None:
        """Stop listening for events."""
        if not self._listener_thread:
            return

        self._stop_event.set()
        if self._listener_thread.is_alive():
            self._listener_thread.join(timeout=2)
        self._listener_thread = None
        self._client_id = None
        self._connected = False

    def is_connected(self) -> bool:
        """Check if the listener is connected to the event stream."""
        return self._connected and bool(
            self._listener_thread and self._listener_thread.is_alive()
        )

    def get_client_id(self) -> Optional[str]:
        """Get the client ID assigned by the server."""
        return self._client_id

    def get_raw_sse(self, timeout: Optional[float] = None) -> Optional[ServerSentEvent]:
        """
        Get next SSE from the queue.
        Args:
            timeout: Maximum time to wait for an event in seconds.
                    If None, will wait indefinitely.
        Returns:
            The next SSE.
        """
        if not self.is_connected():
            raise LabtaskerRuntimeError("Event listener is not connected")
        try:
            return self._event_queue.get(timeout=timeout)
        except Empty:
            return None

    def get_event(self, timeout: Optional[float] = None) -> Optional[EventResponse]:
        """
        Get the next event from the queue. (event only, pings are discarded)

        Args:
            timeout: Maximum time to wait for an event in seconds.
                    If None, will wait indefinitely.

        Returns:
            The next event, or None if timeout is reached.
        """
        if not self.is_connected():
            raise LabtaskerRuntimeError("Event listener is not connected")

        try:
            sse = self._event_queue.get(timeout=timeout)
            if sse.event == "event":
                return EventResponse(**json.loads(sse.data))
            return None  # Skip non-event messages like pings
        except Empty:
            return None

    def iter_events(self) -> Iterator[EventResponse]:
        """
        Iterate over events as they arrive.

        Yields:
            EventResponse objects as they arrive.
        """
        while self.is_connected():
            event = self.get_event(timeout=1.0)  # prevent queue blocking forever
            if event:
                yield event
            time.sleep(0.1)

    def iter_raw_sse(self) -> Iterator[ServerSentEvent]:
        """
        Iterate over raw SSE events as they arrive.
        """
        while self.is_connected():
            sse = self.get_raw_sse(timeout=1.0)
            if sse:
                yield sse
            time.sleep(0.1)

    def retry_context_iter(self, reset: bool = False):
        if reset:
            self._retry_context_iter = stamina.retry_context(
                on=httpx.TransportError,
                attempts=10,
                timeout=100.0,
                wait_initial=0.5,
                wait_max=16.0,
                wait_jitter=1.0,
                wait_exp_base=2.0,
            ).__iter__()
        return self._retry_context_iter

    def _event_listener_thread(self) -> None:
        """Background thread that listens for events from the server."""
        try:
            while not self._stop_event.is_set():
                attempt = next(self.retry_context_iter())
                with attempt:
                    client = get_httpx_client()
                    with connect_sse(
                        client,
                        "GET",
                        "/api/v1/queues/me/events",
                        timeout=300,  # TODO: hard coded
                    ) as event_source:
                        event_source.response.raise_for_status()

                        for sse in event_source.iter_sse():
                            if self._stop_event.is_set():
                                break

                            if sse.event == "connection":
                                # Handle connection event
                                connection_data = json.loads(sse.data)
                                self._client_id = connection_data.get("client_id")
                                self._connected = True

                            # Queue the event for processing
                            self._event_queue.put(sse)
                            # reset retry context, as the retry is intended for **consecutive** failures
                            self.retry_context_iter(reset=True)

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error in event listener: {e}")
            self._error = e
        except httpx.RequestError as e:
            logger.error(f"Request error in event listener: {e}")
            self._error = e
        except Exception as e:
            logger.exception(f"Unexpected error in event listener: {e}")
            self._error = e
        finally:
            self._connected = False


# Convenience functions
def connect_events(timeout: int = 10) -> EventListener:
    """
    Connect to the event stream.

    Args:
        timeout: Maximum time to wait for connection in seconds.

    Returns:
        An EventListener instance.
    """
    return EventListener().start(timeout=timeout)


__all__ = [
    "EventListener",
    "connect_events",
]
