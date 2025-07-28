import os
import time
from collections import defaultdict
from concurrent.futures.thread import ThreadPoolExecutor

import pytest
from typing_extensions import Annotated

from labtasker import Required, create_queue, loop, report_task_status, submit_task
from labtasker.api_models import EventResponse, TaskUpdateRequest
from labtasker.client.core.api import update_tasks
from labtasker.client.core.context import set_current_worker_id
from labtasker.client.core.events import connect_events
from tests.fixtures.logging import silence_logger
from tests.test_client.test_core.test_event.utils import dump_events

if os.environ.get("GITHUB_ACTIONS") == "true":
    pytest.skip(
        f"Skipping {__file__} GH Actions.",
        allow_module_level=True,
    )

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


def job_flow_submit_update_cancel_run():
    num_tasks = 3
    expected = []
    # 1. Submit tasks
    task_ids = []
    for i in range(num_tasks):
        resp = submit_task(task_name=f"test_task_{i}", args={"foo": f"bar_{i}"})
        expected.append(("created", "pending"))
        task_ids.append(resp.task_id)

    # 2. Update args of the tasks
    update_tasks(
        task_updates=[
            TaskUpdateRequest(
                task_id=task_ids[i], args={"baz": f"baz_{i}"}, replace_fields=["args"]
            )  # noqa
            for i in range(num_tasks)
        ],
        reset_pending=True,
    )
    expected.extend(("pending", "pending") for _ in range(num_tasks))

    # 3. Cancel the first task
    report_task_status(task_id=task_ids[0], status="cancelled")
    expected.append(("pending", "cancelled"))

    # 4. Run the rest
    @loop()
    def dummy(baz: Annotated[str, Required()]):
        assert baz.startswith("baz")
        time.sleep(0.1)

    dummy()

    # reset worker ID so that during serial tests, worker ID are created separately
    set_current_worker_id(None)

    expected.append(("created", "active"))  # worker FSM event
    for _ in range(num_tasks - 1):
        expected.append(("pending", "running"))
        expected.append(("running", "success"))

    return expected


def job_flow_submit_only():
    """Flow that only submits tasks without running them"""
    expected = []
    for i in range(2):
        resp = submit_task(
            task_name=f"submit_only_{i}", args={"submit_only": f"value_{i}"}
        )
        expected.append(("created", "pending"))
    return expected


def job_flow_cancel_all():
    """Flow that submits tasks and cancels all of them"""
    expected = []
    task_ids = []
    for i in range(2):
        resp = submit_task(
            task_name=f"cancel_all_{i}", args={"cancel_all": f"value_{i}"}
        )
        expected.append(("created", "pending"))
        task_ids.append(resp.task_id)

    for task_id in task_ids:
        report_task_status(task_id=task_id, status="cancelled")
        expected.append(("pending", "cancelled"))
    return expected


def job_flow_update_and_run():
    """Flow that submits tasks, updates them, and runs them"""
    expected = []
    task_ids = []
    for i in range(2):
        resp = submit_task(task_name=f"update_run_{i}", args={"initial": f"value_{i}"})
        expected.append(("created", "pending"))
        task_ids.append(resp.task_id)

    update_tasks(
        task_updates=[
            TaskUpdateRequest(
                task_id=task_id, args={"updated": "new_value"}, replace_fields=["args"]
            )  # noqa
            for task_id in task_ids
        ],
        reset_pending=True,
    )
    for _ in task_ids:
        expected.append(("pending", "pending"))

    @loop()
    def dummy(updated=Required()):
        assert updated == "new_value"
        time.sleep(0.1)

    dummy()

    # reset worker ID so that during serial tests, worker ID are created separately
    set_current_worker_id(None)

    expected.append(("created", "active"))  # worker FSM event
    for _ in task_ids:
        expected.append(("pending", "running"))
        expected.append(("running", "success"))

    return expected


def fmt_expected(expected):
    for i, (from_state, to_state) in enumerate(expected):
        print(f"{i}: {from_state} -> {to_state}")


def fmt_received(received):
    for i, event_resp in enumerate(received):
        event_resp: EventResponse
        print(f"{i}: {event_resp.event.old_state} -> {event_resp.event.new_state}")


def test_various_actions_serial(db_fixture):  # db_fixture to clean up
    """Test various actions (submit, update, cancel, run) in serial mode"""
    job_flows = {
        "submit_only": job_flow_submit_only,
        "cancel_all": job_flow_cancel_all,
        "update_and_run": job_flow_update_and_run,
        "submit_update_cancel_run": job_flow_submit_update_cancel_run,
    }

    listener = connect_events(timeout=5)

    all_expected = []
    flow_boundaries = {}  # Map flow name to its event range

    try:
        current_index = 0
        for flow_name, flow_handle in job_flows.items():
            flow_boundaries[flow_name] = current_index
            expected = flow_handle()
            all_expected.extend(expected)
            current_index = len(all_expected)
    except Exception as e:
        pytest.fail(f"Error in flow execution: {e}")

    time.sleep(2)
    listener.stop()

    received_events = dump_events(listener)

    if len(received_events) != len(all_expected):
        print("Expected:")
        fmt_expected(all_expected)
        print("Received:")
        fmt_received(received_events)
        assert False, "Number of events does not match"

    # Verify event transitions match expected sequence
    for i, event_resp in enumerate(received_events):
        event_resp: EventResponse
        from_state, to_state = all_expected[i]

        # Identify which flow this event belongs to
        flow_name = next(
            name
            for name, start_idx in flow_boundaries.items()
            if i >= start_idx
            and (
                i < next_start_idx
                if (
                    next_start_idx := flow_boundaries.get(
                        next(iter(flow_boundaries.keys())), len(all_expected)
                    )
                )
                else True
            )
        )

        assert event_resp.event.old_state == from_state, (
            f"Event {i} (Flow '{flow_name}') has wrong from_state: "
            f"{event_resp.event.old_state}, expected {from_state}"
        )
        assert event_resp.event.new_state == to_state, (
            f"Event {i} (Flow '{flow_name}') has wrong to_state: "
            f"{event_resp.event.new_state}, expected {to_state}"
        )


def test_various_actions_parallel(db_fixture):  # db_fixture to clean up
    """Test various actions with multiple concurrent flows"""
    job_flows = {
        "submit_only": job_flow_submit_only,
        "cancel_all": job_flow_cancel_all,
        "update_and_run": job_flow_update_and_run,
        "submit_update_cancel": job_flow_submit_update_cancel_run,
    }

    listener = connect_events(timeout=5)

    with ThreadPoolExecutor(max_workers=len(job_flows)) as executor:
        # Submit all flows with their names and collect futures
        futures = {
            name: executor.submit(flow_handle)
            for name, flow_handle in job_flows.items()
        }

        # Collect expected results from all flows
        expected_results = {}
        for name, future in futures.items():
            try:
                expected_results[name] = future.result()
            except Exception as e:
                pytest.fail(f"Flow '{name}' execution failed: {e}")

    time.sleep(2)
    listener.stop()
    received_events = dump_events(listener)

    # Reduce expected transitions
    expected_counts = defaultdict(int)
    for flow_name, flow_result in expected_results.items():
        for from_state, to_state in flow_result:
            expected_counts[(from_state, to_state)] += 1

    # Reduce actual transitions
    actual_counts = defaultdict(int)
    for event in received_events:
        transition = (event.event.old_state, event.event.new_state)
        actual_counts[transition] += 1

    # Verify counts match for each transition type
    for transition, expected_count in expected_counts.items():
        from_state, to_state = transition
        actual_count = actual_counts[transition]
        assert actual_count == expected_count, (
            f"Transition {from_state}->{to_state}: "
            f"expected {expected_count} events, but got {actual_count}"
        )
