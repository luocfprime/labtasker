import pytest

from labtasker.constants import Priority


@pytest.mark.integration
@pytest.mark.unit
class TestFetchExtraFilter:
    @pytest.fixture
    def setup_tasks(self, db_fixture, queue_args):
        # Setup: Create a queue
        queue_id = db_fixture.create_queue(**queue_args)

        # Create tasks with different attributes
        task_args_1 = {
            "queue_id": queue_id,
            "task_name": "task_a",
            "args": {"arg1": 1},
            "priority": Priority.HIGH,
            "metadata": {"tag": "a"},
        }
        task_args_2 = {
            "queue_id": queue_id,
            "task_name": "task_b",
            "args": {"arg1": 1},
            "priority": Priority.MEDIUM,
            "metadata": {"tag": "b"},
        }
        task_args_3 = {
            "queue_id": queue_id,
            "task_name": "task_c",
            "args": {"arg1": 1},
            "priority": Priority.LOW,
            "metadata": {"tag": "c"},
        }
        task_args_4 = {
            "queue_id": queue_id,
            "task_name": "task_d",
            "args": {"arg1": 1},
            "priority": Priority.LOW,
            "metadata": {"tag": "a"},
        }

        # Create tasks
        db_fixture.create_task(**task_args_1)
        db_fixture.create_task(**task_args_2)
        db_fixture.create_task(**task_args_3)
        db_fixture.create_task(**task_args_4)

        return queue_id

    def test_self_defined_tag(self, db_fixture, setup_tasks):
        queue_id = setup_tasks
        # Test 1. query by self-defined tag
        extra_filter = {"metadata": {"tag": "b"}}

        task = db_fixture.fetch_task(queue_id=queue_id, extra_filter=extra_filter)

        assert task is not None
        assert task["task_name"] == "task_b"

    def test_non_existent_tag(self, db_fixture, setup_tasks):
        queue_id = setup_tasks
        # Test 2. query non-existent tag
        extra_filter = {"metadata": {"tag": "no-exist"}}

        task = db_fixture.fetch_task(queue_id=queue_id, extra_filter=extra_filter)

        assert task is None  # no match

    def test_query_operators(self, db_fixture, setup_tasks):
        queue_id = setup_tasks
        # Test 3. query operators
        extra_filter = {
            "$and": [
                {"metadata.tag": {"$in": ["a", "b"]}},
                {"priority": Priority.LOW},
            ]
        }
        task = db_fixture.fetch_task(queue_id=queue_id, extra_filter=extra_filter)
        assert task is not None
        assert task["task_name"] == "task_d"
