import time
from typing import Dict, List

import pytest
from typing_extensions import Annotated

import labtasker
from labtasker import create_queue, finish, ls_tasks, submit_task, task_info
from labtasker.client.client_api import Required, loop
from tests.fixtures.logging import silence_logger

pytestmark = [
    pytest.mark.unit,
    pytest.mark.integration,
    pytest.mark.e2e,
    pytest.mark.usefixtures(
        "silence_logger"
    ),  # silence logger in testcases of this module
]

TOTAL_TASKS = 3


@pytest.fixture(autouse=True)
def setup_queue(client_config):
    return create_queue(
        queue_name=client_config.queue.queue_name,
        password=client_config.queue.password.get_secret_value(),
        metadata={"tag": "test"},
    )


@pytest.fixture
def setup_tasks(db_fixture):
    # Create a set of test tasks with different arguments
    # The db_fixture ensures the database is cleared after each test
    for i in range(TOTAL_TASKS):
        submit_task(
            task_name=f"test_task_{i}",
            args={
                "arg1": i,
                "arg2": {
                    "arg3": i,
                    "arg4": "foo",
                    "arg5": {"arg6": "bar"},
                },
            },
        )


class TestRegularBehaviour:
    """Test the basic functionality of the task loop without resolvers"""

    def test_job_success(self, setup_tasks):
        # Test that all tasks are successfully processed
        tasks = ls_tasks()
        assert tasks.found
        assert len(tasks.content) == TOTAL_TASKS

        idx = -1

        @loop(required_fields=["arg1", "arg2"], eta_max="1h", pass_args_dict=True)
        def job(args):
            nonlocal idx
            idx += 1
            task_name = task_info().task_name
            # Verify that tasks are processed in the expected order
            assert task_name == f"test_task_{idx}"
            assert args["arg1"] == idx
            assert args["arg2"]["arg3"] == idx

            # Add a small delay to ensure API requests are processed
            time.sleep(0.5)

            finish("success")

        job()

        # Verify all tasks were processed
        assert idx + 1 == TOTAL_TASKS, idx

        # Verify all tasks are marked as successful
        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            assert task.status == "success"

    def test_job_manual_failure(self, setup_tasks):
        """Test behavior when tasks are manually marked as failed"""
        cnt = 0

        max_retries = 3

        @loop(
            required_fields=["arg1", "arg2"],
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
            pass_args_dict=True,
        )
        def job(args):
            nonlocal cnt
            cnt += 1
            # Add a small delay to ensure API requests are processed
            time.sleep(0.5)
            # Manually mark the task as failed
            finish("failed")

        job()

        # Verify the job was retried the expected number of times
        assert cnt == max_retries, cnt

        tasks = ls_tasks()
        assert tasks.found

        total_retries = 0
        for task in tasks.content:
            # All failed tasks should be returned to the queue with pending status
            assert task.status == "pending"
            total_retries += task.retries

        # Verify the total number of retries matches expectations
        assert total_retries == max_retries, total_retries

    def test_job_auto_failure(self, setup_tasks):
        """Test behavior when tasks fail due to an exception"""
        cnt = 0

        max_retries = 3

        @loop(
            required_fields=["arg1", "arg2"],
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
            pass_args_dict=True,
        )
        def job(args):
            nonlocal cnt
            cnt += 1
            # Add a small delay to ensure API requests are processed
            time.sleep(0.5)

            # Force an exception that should be caught by the loop
            assert False

        job()

        # Verify the job was retried the expected number of times
        assert cnt == max_retries, cnt

        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            # All failed tasks should be returned to the queue with pending status
            assert task.status == "pending"


class TestRunnerWithResolver:
    """Test the task loop with argument resolvers"""

    def test_job_success(self, setup_tasks):
        """Test successful task processing with resolvers"""
        tasks = ls_tasks()
        assert tasks.found
        assert len(tasks.content) == TOTAL_TASKS

        idx = -1

        def arg2_arg3_to_str(arg2):
            """A custom resolver that converts arg3 to a string"""
            arg2["arg3"] = str(arg2["arg3"])
            return arg2

        @loop(required_fields=["*"], eta_max="1h")
        def job(
            arg1: Annotated[int, Required()],  # annotation
            arg2: Annotated[dict, Required(resolver=arg2_arg3_to_str)],  # resolver
            arg_bar: str = Required(alias="arg2.arg5.arg6"),  # alias and as default
            task_args=None,
        ):
            nonlocal idx
            idx += 1
            task_name = task_info().task_name
            # Verify tasks are processed in the expected order
            assert task_name == f"test_task_{idx}"
            assert arg1 == idx
            # Verify the resolver converted arg3 to a string
            assert arg2["arg3"] == f"{idx}"
            # Verify the alias correctly extracted the nested value
            assert arg_bar == "bar"

            # Add a small delay to ensure API requests are processed
            time.sleep(0.5)

            finish("success")

        job()

        # Verify all tasks were processed
        assert idx + 1 == TOTAL_TASKS, idx

        # Verify all tasks are marked as successful
        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            assert task.status == "success"

    def test_job_manual_failure(self, setup_tasks):
        """Test behavior when tasks with resolvers are manually marked as failed"""
        cnt = 0

        max_retries = 3

        @loop(
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
        )
        def job(
            arg1: Annotated[int, Required()],
            arg2: Annotated[dict, Required()],
            task_args=None,
        ):
            nonlocal cnt
            cnt += 1
            # Add a small delay to ensure API requests are processed
            time.sleep(0.5)
            # Manually mark the task as failed
            finish("failed")

        job()

        # Verify the job was retried the expected number of times
        assert cnt == max_retries, cnt

        tasks = ls_tasks()
        assert tasks.found

        total_retries = 0
        for task in tasks.content:
            # All failed tasks should be returned to the queue with pending status
            assert task.status == "pending"
            total_retries += task.retries

        # Verify the total number of retries matches expectations
        assert total_retries == max_retries, total_retries

    def test_job_auto_failure(self, setup_tasks):
        """Test behavior when tasks with resolvers fail due to an exception"""
        cnt = 0

        max_retries = 3

        @loop(
            eta_max="1h",
            create_worker_kwargs={"max_retries": max_retries},
        )
        def job(
            arg1: Annotated[int, Required()],
            arg2: Annotated[dict, Required()],
            task_args=None,
        ):
            nonlocal cnt
            cnt += 1
            # Add a small delay to ensure API requests are processed
            time.sleep(0.5)

            # Force an exception that should be caught by the loop
            assert False

        job()

        # Verify the job was retried the expected number of times
        assert cnt == max_retries, cnt

        tasks = ls_tasks()
        assert tasks.found
        for task in tasks.content:
            # All failed tasks should be returned to the queue with pending status
            assert task.status == "pending"


class TestRunnerFetchTasks:
    """Test complex task argument extraction and filtering scenarios"""

    GROUPS = 6
    TASK_PER_GROUP = 2

    @pytest.fixture
    def setup_tasks(self):
        """Create multiple groups of tasks with different argument structures"""
        GROUPS = self.GROUPS
        TASK_PER_GROUP = self.TASK_PER_GROUP

        count = [TASK_PER_GROUP] * GROUPS

        # Group 1: Basic argument types
        args_grp_1 = {
            "arg1": [1, 2, 3],
            "arg2": 0,
            "arg3": "foo",
            "arg4": {0: "zero", 1: "one"},
        }

        # Group 2: Nested dictionaries and arrays
        args_grp_2 = {
            "arg1": [1, 2, 3],
            "arg2": [
                {
                    "arg31": {
                        "arg41": ["foo1", "bar1", "baz1"],
                    },
                    "args51": {"arg6": False},
                },
                {
                    "arg32": {
                        "arg42": ["foo2", "bar2", "baz2"],
                    },
                    "args52": {"arg6": False},
                },
            ],
        }

        # Group 3: Same structure as group 2 (for testing filters)
        args_grp_3 = args_grp_2

        # Group 4: Arguments with dot notation in keys (dot-sep fields is expected to be unflattened into hierarchical dict)
        args_grp_4 = {
            "arg1": "value1",
            "arg2.arg21": "key with dots",
            "nested": {"field1": 1, "field2": 2},
        }

        # Group 5: Another nested structure
        args_grp_5 = {
            "arg1": "value1",
            "arg2": {
                "arg21": 1,
                "arg22": 2,
                "arg23": {
                    "arg231": 1,
                    "arg232": 2,
                },
            },
        }

        # Group 6: Another deeply nested
        args_grp_6 = {
            "arg1": "value1",
            "arg2": {
                "arg21": [1, 2, 3],
                "arg22": {
                    "deep1": {"deeper1": ["a", "b", "c"], "deeper2": {"bottom": True}},
                    "deep2": "simple string",
                },
            },
        }

        arg_groups = {
            1: args_grp_1,
            2: args_grp_2,
            3: args_grp_3,
            4: args_grp_4,
            5: args_grp_5,
            6: args_grp_6,
        }

        # Create tasks for each group
        for i in range(GROUPS):
            for j in range(count[i]):
                submit_task(
                    task_name=f"test_task_{i * GROUPS + j}",
                    args=arg_groups[i + 1],  # i+1 to match the 1-based group numbers
                    metadata={"group": i + 1},
                )

        return count

    def test_fetch_and_run_group_3(self, setup_tasks):
        """Test filtering tasks by metadata group"""
        cnt = 0

        @loop(
            extra_filter={
                "metadata.group": {
                    "$nin": [1, 2, 4, 5, 6]
                },  # Filter out all groups except group 3
            },
        )
        def job(
            arg1: List[int] = Required(),
            arg2: List[dict] = Required(),
        ):
            nonlocal cnt
            cnt += 1

            # Verify we're only processing group 3 tasks
            assert labtasker.task_info().metadata["group"] == 3
            assert arg1 == [1, 2, 3]
            assert len(arg2) == 2
            assert arg2[0]["arg31"]["arg41"] == ["foo1", "bar1", "baz1"]

            # Add a small delay to ensure API requests are processed
            time.sleep(0.5)

            finish("success")

        job()

        # Verify we processed the expected number of tasks from group 3
        assert cnt == setup_tasks[2], cnt

    def test_fetch_leaf_field(self, setup_tasks):
        """Test extracting specific leaf fields from deeply nested structures"""
        cnt = 0

        @loop(
            extra_filter={"metadata.group": 5},  # Only run on group 5
            # Specify required fields to satisfy the "no more, no less" principle
            # required_fields is merged with those specified using Required(...)
            required_fields=["arg1", "arg2.arg23.arg232"],
        )
        def job(
            field1: Annotated[int, Required(alias="arg2.arg21")],
            field2: Annotated[int, Required(alias="arg2.arg22")],
            field3: Annotated[int, Required(alias="arg2.arg23.arg231")],
        ):
            nonlocal cnt
            cnt += 1

            # Verify values are correctly extracted from nested paths
            assert field1 == 1
            assert field2 == 2
            assert field3 == 1

            time.sleep(0.5)
            finish("success")

        job()

        # Verify we processed the expected number of tasks from group 5
        assert cnt == setup_tasks[4], cnt  # Group 5 is at index 4

    def test_fetch_root_field(self, setup_tasks):
        """Test fetching an entire nested dictionary from field root. i.e. arg1, arg2"""
        cnt = 0

        @loop(extra_filter={"metadata.group": 5})  # Only run on group 5
        def job(
            value: Annotated[str, Required(alias="arg1")],
            nested_dict: Annotated[dict, Required(alias="arg2")],
        ):
            nonlocal cnt
            cnt += 1

            # Verify we got the entire nested structure intact
            assert value == "value1"
            assert nested_dict["arg21"] == 1
            assert nested_dict["arg22"] == 2
            assert nested_dict["arg23"]["arg231"] == 1
            assert nested_dict["arg23"]["arg232"] == 2

            time.sleep(0.5)
            finish("success")

        job()

        # Verify we processed the expected number of tasks from group 5
        assert cnt == setup_tasks[4], cnt

    def test_fetch_with_submitting_dotted_key(self, setup_tasks):
        """Test fetching a task that was submitted with dotted fields (which should be un-flattened into a hierarchical dict structure)"""
        cnt = 0

        @loop(
            required_fields=["arg1", "arg2.arg21", "nested"],
            extra_filter={"metadata.group": 4},  # Only run on group 4
        )
        def job(arg2: Annotated[Dict[str, str], Required(alias="arg2")]):
            nonlocal cnt
            cnt += 1

            # When a task is submitted with "arg2.arg21", it's un-flattened to args["arg2"]["arg21"]
            assert arg2["arg21"] == "key with dots"

            time.sleep(0.5)
            finish("success")

        job()

        # Verify we processed the expected number of tasks from group 4
        assert cnt == setup_tasks[3], cnt  # Group 4 is at index 3

    def test_fetch_star_matching(self, setup_tasks):
        """Test using wildcard "*" to match all required fields"""
        cnt = 0

        @loop(
            required_fields=["*"],  # Match all fields
        )
        def job(
            array_value: Annotated[list, Required(alias="arg2.arg21")],
            deep_array: Annotated[list, Required(alias="arg2.arg22.deep1.deeper1")],
            boolean_value: Annotated[
                bool, Required(alias="arg2.arg22.deep1.deeper2.bottom")
            ],
        ):
            nonlocal cnt
            cnt += 1

            # Verify deeply nested values are correctly extracted
            assert array_value == [1, 2, 3]
            assert deep_array == ["a", "b", "c"]
            assert boolean_value is True

            time.sleep(0.5)
            finish("success")

        job()

        # Despite required_fields=["*"], the required 'arg2.arg22.deep1.deeper1' only
        # exists in group 6, therefore only group 6 should be fetched
        assert cnt == setup_tasks[5], cnt  # Group 6 is at index 5

    def test_multiple_path_formats(self, setup_tasks):
        """
        Note on accessing list elements:

        Accessing list elements using syntax like 'arg2.0' does not work by design.
        This is because '0' could be a valid dictionary key, causing ambiguity.

        The recommended approach to access list elements is to retrieve the entire list:
        arg2: List[Any] = Required()

        And then access elements using standard indexing: arg2[0]
        """
        # This test is commented out because the described functionality is not supported
        # The following code is just for demo purpose
        # cnt = 0
        #
        # @loop(required_fields=["*"], extra_filter={"metadata.group": 2})  # Only run on group 2
        # def job(
        #     # Direct array access
        #     array: Annotated[list, Required(alias="arg1")],
        #     # Access a nested field from an array item
        #     nested_array: Annotated[list, Required(alias="arg2.0.arg31.arg41")],
        #     # Access a boolean from a different nested path
        #     boolean: Annotated[bool, Required(alias="arg2.0.args51.arg6")],
        # ):
        #     nonlocal cnt
        #     cnt += 1
        #
        #     # Verify all types of paths work
        #     assert array == [1, 2, 3]
        #     assert nested_array == ["foo1", "bar1", "baz1"]
        #     assert boolean is False
        #
        #     time.sleep(0.5)
        #     finish("success")
        #
        # job()
        #
        # assert cnt == setup_tasks[1], cnt  # Group 2 is at index 1

    def test_number_as_key(self, setup_tasks):
        """
        Expected Behaviour: When submitting task like with args like "arg4": {0: "zero", 1: "one"},
        the keys are treated as strings.
        When fetching the task, the keys remain as strings, and are not converted back to primitive types.
        """
        cnt = 0

        @loop(
            required_fields=["*"],
            extra_filter={"metadata.group": 1},  # Only run on group 1
        )
        def job(arg4: Dict[str, str] = Required()):
            nonlocal cnt
            cnt += 1

            # Numeric keys in dictionaries are converted to strings
            # This is expected behavior when working with JSON-like data
            assert arg4["0"] == "zero"
            assert arg4["1"] == "one"

            time.sleep(0.5)
            finish("success")

        job()

        # Verify we processed the expected number of tasks from group 1
        assert cnt == setup_tasks[0], cnt  # Group 1 is at index 0

    def test_fetch_using_task_id(self, setup_tasks):
        task = ls_tasks().content[0]
        task_name = task.task_name
        task_id = task.task_id

        @loop(
            required_fields=["*"],
            extra_filter={"task_id": task_id},
        )
        def job(
            arg2: Annotated[Dict[str, str], Required(alias="arg2.arg21")],
        ):
            assert task_info().task_name == task_name

        job()
