"""
End-to-end tests for the EventListener class that checks entity data.
"""

import threading
import time

import pytest

from labtasker import Required, create_queue, loop, submit_task
from labtasker.api_models import EventResponse
from labtasker.client.core.events import connect_events
from tests.fixtures.logging import silence_logger
from tests.test_client.test_core.test_event.utils import dump_events

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("silence_logger"),
]


@pytest.fixture(autouse=True)
def setup_queue(client_config, db_fixture):
    # relies on db_fixture so that DB is cleaned up after each test
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


def test_event_listener_entity_data():
    """Test the basic flow of events when tasks are submitted and processed."""
    job_finish_event = threading.Event()
    listener = connect_events(timeout=5)

    def jobflow_thread():
        try:
            # Submit tasks to generate events
            task_id = submit_task(
                task_name="test_task",
                args={"foo": "bar"},
                max_retries=1,  # only 1 attempt
            ).task_id

            @loop()
            def dummy(foo=Required()):
                time.sleep(0.5)
                raise RuntimeError  # crash task

            dummy()  # fetch and run tasks
        except Exception as e:
            pytest.fail(f"Error in jobflow thread: {e}")
        finally:
            job_finish_event.set()

    jobflow_thread = threading.Thread(target=jobflow_thread, daemon=True)

    time.sleep(1)  # wait for the listener to start
    jobflow_thread.start()

    # Wait for job to finish with timeout
    job_finish_event.wait(timeout=10)
    # Give some time for all events to be processed
    time.sleep(2)
    listener.stop()

    # Check that we received the expected events
    received_events = dump_events(listener)

    expected_transition_sequence = [
        # 1 job creation events
        ("created", "pending"),
        # worker creation event
        ("created", "active"),
        # 1 running and failure events
        ("pending", "running"),
        # worker fail() event result in either active -> active or active -> crashed
        ("active", "active"),
        # task fail() event
        ("running", "failed"),
    ]

    assert len(received_events) == len(
        expected_transition_sequence
    ), f"Not enough events, got {len(received_events)} / {len(expected_transition_sequence)}"

    # Verify event transitions match expected sequence
    for i, event_resp in enumerate(received_events):
        event_resp: EventResponse
        from_state, to_state = expected_transition_sequence[i]
        assert (
            event_resp.event.old_state == from_state
        ), f"Event {i} has wrong from_state: {event_resp.event.old_state}, expected {from_state}"
        assert (
            event_resp.event.new_state == to_state
        ), f"Event {i} has wrong to_state: {event_resp.event.new_state}, expected {to_state}"

        print(f"Event data: {event_resp.event.entity_data}")

    # assert cmd in pending -> running event
    assert received_events[2].event.entity_data["cmd"], "Cmd is missing"

    # assert summary in running -> failed event
    assert received_events[-1].event.entity_data["summary"], "Summary is missing"

    # Join threads to clean up
    jobflow_thread.join(timeout=3)
