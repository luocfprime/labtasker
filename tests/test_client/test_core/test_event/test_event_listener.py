"""
End-to-end tests for the EventListener class.
"""

import threading
import time
from queue import Queue

import pytest

from labtasker import create_queue, report_task_status, submit_task
from labtasker.api_models import StateTransitionEvent
from labtasker.client.core.config import get_client_config
from labtasker.client.core.events import EventListener, connect_events
from tests.fixtures.logging import silence_logger

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("silence_logger"),
]


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


def test_event_listener_basic_flow():
    """Test the basic flow of events when tasks are submitted and processed."""
    events_received = Queue()
    stop_event = threading.Event()

    # Thread 1. Event listener
    def event_listener_thread():
        # Use the queue_id directly with the EventListener
        listener = connect_events(timeout=5)
        try:
            for event in listener.iter_events(timeout=0.5):
                if stop_event.is_set():
                    break
                if event and hasattr(event.event, "entity_id"):
                    events_received.put(event)
        finally:
            listener.stop()

    def jobflow_thread():
        try:
            # Submit tasks to generate events
            task_ids = []
            for i in range(3):
                task_id = submit_task(
                    task_name=f"test_task_{i}", args={"foo": f"bar_{i}"}
                ).task_id
                task_ids.append(task_id)

            # Cancel the first task
            report_task_status(task_id=task_ids[0], status="cancelled")

            # Fetch and run other tasks
            for task_id in task_ids:
                report_task_status(task_id, "success")
                time.sleep(0.5)

            # Wait for events to be processed
            time.sleep(3)

            # Check that we received the expected events
            received_events = []
            while not events_received.empty():
                received_events.append(events_received.get())

            # We should have at least 6 events (3 task creations + 3 status updates)
            assert len(received_events) >= 6

            # Verify that we received events for our tasks
            task_creation_events = [
                e
                for e in received_events
                if isinstance(e.event, StateTransitionEvent)
                and e.event.entity_type == "task"
                and e.event.new_state == "pending"
            ]

            task_completion_events = [
                e
                for e in received_events
                if isinstance(e.event, StateTransitionEvent)
                and e.event.entity_type == "task"
                and e.event.new_state == "success"
            ]

            # Verify we got creation events for all tasks
            assert len(task_creation_events) >= 3

            # Verify we got completion events for all tasks
            assert len(task_completion_events) >= 3

            # Verify the task IDs match what we submitted
            event_task_ids = [e.event.entity_id for e in task_creation_events]
            for task_id in task_ids:
                assert task_id in event_task_ids

        finally:
            # Clean up
            stop_event.set()
            listener_thread.join(timeout=5)

    listener_thread = threading.Thread(target=event_listener_thread, daemon=True)
    listener_thread.start()

    # Give the listener time to connect
    time.sleep(2)


def test_event_listener_reconnection():
    """Test that the event listener can reconnect after being stopped."""
    # Create a unique queue for testing
    config = get_client_config()
    queue_id = create_queue(
        queue_name=config.queue.queue_name,
        password=config.queue.password.get_secret_value(),
    ).queue_id

    # First connection
    listener1 = connect_events(timeout=5)
    assert listener1.is_connected() is True
    client_id1 = listener1.get_client_id()
    assert client_id1 is not None
    listener1.stop()

    # Wait a moment
    time.sleep(1)

    # Second connection
    listener2 = connect_events(timeout=5)
    assert listener2.is_connected() is True
    client_id2 = listener2.get_client_id()
    assert client_id2 is not None

    # Client IDs should be different for each connection
    assert client_id1 != client_id2

    # Clean up
    listener2.stop()


def test_event_listener_multiple_queues():
    """Test that we can listen to events from multiple queues simultaneously."""
    # Create two unique queues using config
    config = get_client_config()
    queue_id1 = create_queue(
        queue_name=config.queue.queue_name + "-1",
        password=config.queue.password.get_secret_value(),
    ).queue_id
    queue_id2 = create_queue(
        queue_name=config.queue.queue_name + "-2",
        password=config.queue.password.get_secret_value(),
    ).queue_id

    # Start listeners for both queues
    events_queue1 = Queue()
    events_queue2 = Queue()
    stop_event = threading.Event()

    def listener_thread(queue_id, events_queue):
        listener = EventListener(queue_id)
        listener.start(timeout=5)
        try:
            for event in listener.iter_events(timeout=0.5):
                if stop_event.is_set():
                    break
                if event and hasattr(event.event, "entity_id"):
                    events_queue.put(event)
        finally:
            listener.stop()

    thread1 = threading.Thread(target=listener_thread, args=(queue_id1, events_queue1))
    thread2 = threading.Thread(target=listener_thread, args=(queue_id2, events_queue2))
    thread1.daemon = True
    thread2.daemon = True
    thread1.start()
    thread2.start()

    # Give listeners time to connect
    time.sleep(2)

    try:
        # Submit tasks to both queues
        task_id1 = submit_task(
            task_name="test_task_queue1",
            args={"message": "test_queue1"},
        )

        task_id2 = submit_task(
            task_name="test_task_queue2",
            args={"message": "test_queue2"},
        )

        # Wait for events to be processed
        time.sleep(3)

        # Check that each listener received events only for its queue
        queue1_events = []
        while not events_queue1.empty():
            queue1_events.append(events_queue1.get())

        queue2_events = []
        while not events_queue2.empty():
            queue2_events.append(events_queue2.get())

        # Verify we got events for each queue
        assert len(queue1_events) > 0
        assert len(queue2_events) > 0

        # Verify the events are for the correct tasks
        queue1_task_ids = [
            e.event.entity_id
            for e in queue1_events
            if isinstance(e.event, StateTransitionEvent)
        ]
        queue2_task_ids = [
            e.event.entity_id
            for e in queue2_events
            if isinstance(e.event, StateTransitionEvent)
        ]

        assert task_id1 in queue1_task_ids
        assert task_id2 in queue2_task_ids

    finally:
        # Clean up
        stop_event.set()
        thread1.join(timeout=5)
        thread2.join(timeout=5)
