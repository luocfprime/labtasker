import asyncio
from typing import AsyncGenerator, Awaitable, Callable, Dict, Optional, Set

from sse_starlette import ServerSentEvent

from labtasker.api_models import (
    BaseEventModel,
    EventResponse,
    EventSubscriptionResponse,
)
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
        self.current_event: Optional[QueueEvent] = None
        self.current_receivers: Set[str] = set()
        self.sequence = 0

    def publish(self, event: BaseEventModel) -> None:
        """Publish a new event to the queue"""
        self.sequence += 1
        self.current_event = QueueEvent(
            sequence=self.sequence,
            event=event,
        )
        self.current_receivers.clear()

    async def subscribe(
        self, client_id: str, disconnect_handle: Callable[[], Awaitable[bool]]
    ) -> AsyncGenerator[ServerSentEvent, None]:
        """Subscribe to events"""
        # Send initial connection message
        connection_event = EventSubscriptionResponse(
            status="connected", client_id=client_id
        )
        yield ServerSentEvent(
            data=connection_event.model_dump_json(),
            event="connection",
            id=str(self.sequence),
            retry=3000,  # Retry connection after 3 seconds
        )

        last_ping = asyncio.get_event_loop().time()
        try:
            while True:
                # Yield control to event loop first
                await asyncio.sleep(0)

                if await disconnect_handle():
                    break

                current_time = asyncio.get_event_loop().time()
                if current_time - last_ping >= 15:
                    yield ServerSentEvent(event="ping")
                    last_ping = current_time

                if self.current_event and client_id not in self.current_receivers:
                    self.current_receivers.add(client_id)
                    event_response = EventResponse(
                        sequence=self.current_event.sequence,
                        timestamp=self.current_event.timestamp,
                        event=self.current_event.event,
                    )
                    yield ServerSentEvent(
                        data=event_response.model_dump_json(),
                        id=str(self.current_event.sequence),
                        event="event",
                    )

                # Use a shorter sleep interval
                await asyncio.sleep(0.01)
        finally:
            pass

    # Remove the _send_ping method as it's no longer needed


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
