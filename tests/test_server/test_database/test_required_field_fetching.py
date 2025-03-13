import fastapi.exceptions
import pytest

from labtasker.constants import Priority


@pytest.mark.integration
@pytest.mark.unit
class TestTaskRequiredFieldFetching:
    """Tests for task fetching based on required fields."""

    def test_fetch_leaf_match(self, db_fixture, queue_args):
        """Test fetching a task with a full leaf match of required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_leaf_match",
                "args": {"arg1": "value1", "arg2": {"arg21": 1, "arg22": 2}},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_partial_match",
                "args": {"arg1": "value1"},
                "priority": Priority.MEDIUM,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = ["arg1", "arg2.arg21", "arg2.arg22"]

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is not None
        assert task["task_name"] == "task_leaf_match"

        # Try fetch again
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is None

    def test_fetch_non_leaf_match(self, db_fixture, queue_args):
        """Test fetching a task with a non-leaf node match of required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_1",
                "args": {
                    "arg1": "value1",
                    "arg2": {
                        "arg21": 1,
                        "arg22": 2,
                    },
                    "arg3": {
                        "arg31": {
                            "arg311": 1,
                            "arg312": 2,
                        },
                        "arg32": {
                            "arg321": 1,
                            "arg322": 2,
                        },
                    },
                },
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_2",
                "args": {
                    "arg1": "value1",
                },
                "priority": Priority.MEDIUM,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = ["arg1", "arg2", "arg3.arg31", "arg3.arg32"]

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is not None
        assert task["task_name"] == "task_1"

        # Try fetch again
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is None

    def test_fetch_field_partially_overlap(self, db_fixture, queue_args):
        """Test fetching a task with a fields overlapping each other"""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_1",
                "args": {
                    "arg1": "value1",
                    "arg2": {
                        "arg21": 1,
                        "arg22": 2,
                        "arg23": {
                            "arg231": 1,
                            "arg232": 2,
                        },
                    },
                },
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_2",
                "args": {
                    "arg1": "value1",
                    "arg2": {
                        "arg21": 1,
                    },
                },
                "priority": Priority.MEDIUM,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = ["arg1", "arg2", "arg2.arg22"]

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is not None
        assert task["task_name"] == "task_1"

        # Try fetch again
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is None

    def test_fetch_no_match(self, db_fixture, queue_args):
        """Test fetching a task with no matching required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_no_match",
                "args": {"arg2": {"arg21": 1}},
                "priority": Priority.LOW,
            }
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = ["arg1"]

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is None

    def test_fetch_with_multiple_matches(self, db_fixture, queue_args):
        """Test fetching tasks when multiple tasks match the required fields."""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_match_1",
                "args": {"arg1": "value1", "arg2": {"arg21": 1}},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_match_2",
                "args": {"arg1": "value1", "arg2": {"arg21": 1}},
                "priority": Priority.HIGH,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = ["arg1", "arg2.arg21"]

        # Fetch task and assert
        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is not None
        # Check if it fetched the one with the highest priority
        assert task["task_name"] == "task_match_2"

    def test_fetch_star_matching(self, db_fixture, queue_args):
        """Test posing no constraint on the task args by setting '*' as required_fields"""
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_1",
                "args": {"arg2": {"arg21": 1}},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_2",
                "args": {"foo": 0},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_3",
                "args": {"bar": {"baz": 1}, "boo": False},
                "priority": Priority.LOW,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        # Define required fields
        required_fields = ["*"]

        # Fetch task and assert
        for i in range(3):
            task = db_fixture.fetch_task(
                queue_id=queue_id, required_fields=required_fields
            )
            assert task is not None

        task = db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
        assert task is None, "There should not be any more tasks left."

    def test_fetch_with_incorrect_format(self, db_fixture, queue_args):
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks
        task_args = [
            {
                "queue_id": queue_id,
                "task_name": "task_match_1",
                "args": {"arg1": "value1", "arg2": {"arg21": 1}},
                "priority": Priority.LOW,
            },
            {
                "queue_id": queue_id,
                "task_name": "task_match_2",
                "args": {"arg1": "value1", "arg2": {"arg21": 1}},
                "priority": Priority.HIGH,
            },
        ]

        for args in task_args:
            db_fixture.create_task(**args)

        required_fields = [".arg1", ".arg2.arg21"]
        with pytest.raises(fastapi.exceptions.HTTPException):
            db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)

        required_fields = [""]
        with pytest.raises(fastapi.exceptions.HTTPException):
            db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)

        required_fields = ["."]
        with pytest.raises(fastapi.exceptions.HTTPException):
            db_fixture.fetch_task(queue_id=queue_id, required_fields=required_fields)
