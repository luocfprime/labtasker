import json
from typing import List

from labtasker.api_models import EventResponse
from labtasker.client.core.events import EventListener


def dump_events(listener: EventListener) -> List[EventResponse]:
    result = []
    while not listener._event_queue.empty():
        sse = listener._event_queue.get()
        if sse.event == "event":
            result.append(EventResponse(**json.loads(sse.data)))

    return result
