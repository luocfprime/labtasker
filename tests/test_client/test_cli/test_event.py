import re
import subprocess
import threading
import time
from typing import List, Tuple

import pytest

from labtasker import Required, loop, report_task_status, submit_task
from tests.fixtures.logging import silence_logger
from tests.test_client.test_cli.test_queue import cli_create_queue_from_config

# Only e2e test is supported for event related operations.
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.usefixtures("silence_logger"),
]

# Globals
job_finish_event = threading.Event()


def jobflow():
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


def parse_transition(output: str) -> List[Tuple[str, str]]:
    matches = re.finditer(
        r"\[\s*(\w+)[\s\n]*->[\s\n]*(\w+)\s*\]", output, re.DOTALL  # noqa
    )
    transitions = []
    for match in matches:
        from_state = match.group(1)
        to_state = match.group(2)
        transitions.append((from_state, to_state))
    return transitions


@pytest.fixture(autouse=True)
def setup_teardown_db(db_fixture):
    yield


class TestListen:
    def test_listen_basic(self, cli_create_queue_from_config):
        """Test the basic flow of events when tasks are submitted and processed."""
        # Start the CLI process with a timeout
        cli_process = subprocess.Popen(
            ["labtasker", "event", "listen", "--compact"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )

        # Give the CLI process time to start
        time.sleep(5.0)

        # Run the job flow in a thread
        jobflow_thread = threading.Thread(target=jobflow, daemon=True)
        jobflow_thread.start()

        # Wait for job flow to complete
        job_finish_event.wait(timeout=10)
        time.sleep(2.0)  # Give time for events to be processed

        # Terminate the CLI process
        cli_process.terminate()
        stdout, stderr = cli_process.communicate(timeout=5)

        # Parse the output
        received_events = parse_transition(stdout)

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

        # Verify all expected transitions occurred
        assert len(received_events) == len(expected_transition_sequence), (
            f"Expected {len(expected_transition_sequence)} transitions, "
            f"but got {len(received_events)}\nOutput: {stdout}"
        )

        for i, (expected_from, expected_to) in enumerate(expected_transition_sequence):
            actual_from, actual_to = received_events[i]
            assert actual_from == expected_from, (
                f"Transition {i}: expected from state '{expected_from}', "
                f"but got '{actual_from}'"
            )
            assert actual_to == expected_to, (
                f"Transition {i}: expected to state '{expected_to}', "
                f"but got '{actual_to}'"
            )
