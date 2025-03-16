"""
End-to-end tests for the EventListener class.
"""

import threading
import time

import pytest

from labtasker import Required, create_queue, loop, report_task_status, submit_task
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


def test_event_listener_basic_jobflow():
    """Test the basic flow of events when tasks are submitted and processed."""
    job_finish_event = threading.Event()
    listener = connect_events(timeout=5)

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

            @loop()
            def dummy(foo=Required()):
                time.sleep(0.5)

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
        # 3 job creation events
        ("created", "pending"),
        ("created", "pending"),
        ("created", "pending"),
        # 1 cancelled event
        ("pending", "cancelled"),
        # worker creation event
        ("created", "active"),
        # 2 running and success events
        ("pending", "running"),
        ("running", "success"),
        ("pending", "running"),
        ("running", "success"),
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

    # Join threads to clean up
    jobflow_thread.join(timeout=3)
