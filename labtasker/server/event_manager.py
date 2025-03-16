import asyncio
from typing import AsyncGenerator, Awaitable, Callable, Dict

from sse_starlette import ServerSentEvent

from labtasker.api_models import (
    BaseEventModel,
    EventResponse,
    EventSubscriptionResponse,
)
from labtasker.server.config import get_server_config
from labtasker.server.logging import logger
from labtasker.utils import get_current_time


class QueueEvent:
    """Represents the current event in the queue"""

    def __init__(self, sequence: int, event: BaseEventModel):
        self.sequence = sequence
        self.event = event
        self.timestamp = get_current_time()


class QueueEventManager:
    def __init__(self, queue_id: str):
        self.queue_id = queue_id
        self.sequence = 0
        self.client_buffers: Dict[str, asyncio.Queue[QueueEvent]] = {}
        self.max_buffer_size = get_server_config().event_buffer_size

    def publish(self, event: BaseEventModel) -> None:
        """Publish a new event to all client buffers"""
        self.sequence += 1
        queue_event = QueueEvent(
            sequence=self.sequence,
            event=event,
        )
        # Broadcast to all client buffers
        for client_buffer in self.client_buffers.values():
            while True:
                try:
                    client_buffer.put_nowait(queue_event)
                    break
                except asyncio.QueueFull:
                    try:
                        # Remove oldest event
                        client_buffer.get_nowait()
                        logger.warning(
                            "Event queue is full. Dropped oldest event to make room for new one."
                        )
                    except asyncio.QueueEmpty:
                        logger.error("Queue unexpectedly empty after full.")
                        break

    async def subscribe(
        self, client_id: str, disconnect_handle: Callable[[], Awaitable[bool]]
    ) -> AsyncGenerator[ServerSentEvent, None]:
        """Subscribe to events"""
        # Create buffer for this client
        self.client_buffers[client_id] = asyncio.Queue(maxsize=self.max_buffer_size)

        try:
            # Send initial connection message
            connection_event = EventSubscriptionResponse(
                status="connected", client_id=client_id
            )
            yield ServerSentEvent(
                data=connection_event.model_dump_json(),
                event="connection",
                retry=3000,  # Retry connection after 3 seconds
            )

            last_ping = asyncio.get_event_loop().time()

            # Process events from client's buffer
            while not await disconnect_handle():
                # Check if we need to send a ping
                current_time = asyncio.get_event_loop().time()
                if current_time - last_ping > get_server_config().sse_ping_interval:
                    yield ServerSentEvent(event="ping")
                    last_ping = current_time

                # Check for events (non-blocking)
                if not self.client_buffers[client_id].empty():
                    queue_event = await self.client_buffers[client_id].get()
                    event_response = EventResponse(
                        sequence=queue_event.sequence,
                        timestamp=queue_event.timestamp,
                        event=queue_event.event,
                    )
                    yield ServerSentEvent(
                        data=event_response.model_dump_json(),
                        event="event",
                    )
                else:
                    # No events, sleep briefly to avoid CPU spinning
                    await asyncio.sleep(0.1)

        finally:
            # Cleanup client buffer
            if client_id in self.client_buffers:
                del self.client_buffers[client_id]


class EventManager:
    def __init__(self):
        self.queues: Dict[str, QueueEventManager] = {}

    def get_queue_event_manager(self, queue_id: str) -> QueueEventManager:
        if queue_id not in self.queues:
            self.queues[queue_id] = QueueEventManager(queue_id)
        return self.queues[queue_id]

    def publish_event(self, queue_id: str, event: BaseEventModel) -> None:
        """Publish event to queue"""
        queue_manager = self.get_queue_event_manager(queue_id)
        queue_manager.publish(event)


# Global event manager
event_manager = EventManager()
