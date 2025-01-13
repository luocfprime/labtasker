import pytest
from mongomock import MongoClient as MockMongoClient
from pymongo import MongoClient as RealMongoClient

from labtasker.server.database import DatabaseClient


@pytest.fixture
def mock_session():
    """Mock MongoDB session for testing."""

    class MockSession:
        def __init__(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def start_transaction(self):
            return self

        def commit_transaction(self):
            pass

        def abort_transaction(self):
            pass

    return MockSession()


@pytest.fixture
def mock_db(monkeypatch, mock_session):
    """Create a mock database for testing."""
    client = MockMongoClient()
    client.drop_database("test_db")
    db = DatabaseClient(client=client, db_name="test_db")

    # Patch MongoDB operations to ignore session parameter
    def ignore_session(original_method):
        def wrapper(*args, session=None, **kwargs):
            # Remove session parameter
            return original_method(*args, **kwargs)

        return wrapper

    # Patch collection methods to ignore session
    patched_methods = [
        "find_one",
        "insert_one",
        "update_one",
        "delete_one",
        "find",
        "update_many",
        "find_one_and_update",
    ]
    for method in patched_methods:
        for collection in [db._queues, db._tasks, db._workers]:
            original = getattr(collection, method)
            monkeypatch.setattr(collection, method, ignore_session(original))

    # Patch start_session
    monkeypatch.setattr(db._client, "start_session", lambda: mock_session)

    return db


# @pytest.fixture
# def real_db():
#     client = RealMongoClient(
#         # TODO
#     )
#     db = DatabaseClient(client=client, db_name="test_db")
#     return db


def is_mongo_ready(host, port):
    """
    Check if the MongoDB service is ready by running a 'ping' command.
    """
    try:
        client = RealMongoClient(host=host, port=port, serverSelectionTimeoutMS=1000)
        client.admin.command("ping")
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def real_db(docker_services, docker_ip):
    """
    Connect to a real MongoDB instance running in a Docker container.

    This fixture starts a MongoDB container using pytest-docker, waits for the service
    to be ready, and provides a `DatabaseClient` object for interacting with the database.
    """
    # Start the MongoDB service
    docker_services.start("mongo")

    # Get the MongoDB service's host and port
    port = docker_services.port_for("mongo", 27017)
    host = docker_ip

    # Wait for MongoDB to be ready
    docker_services.wait_for_service(
        "mongo",
        timeout=30.0,  # Wait up to 30 seconds
        interval=1.0,  # Check every second
        check=lambda: is_mongo_ready(host, port),
    )

    # Connect to MongoDB using the connection details
    client = RealMongoClient(
        host=host,
        port=port,
        username="root",
        password="example",  # Credentials from docker-compose.yml
        serverSelectionTimeoutMS=5000,  # 5-second timeout for server selection
    )

    # Create a DatabaseClient object
    db = DatabaseClient(client=client, db_name="test_db")

    # Drop the test database before running tests to ensure a clean state
    client.drop_database("test_db")

    return db


@pytest.fixture
def queue_args():
    """Minimum queue args for db create_queue for testing."""
    return {
        "queue_name": "test_queue",
        "password": "test_password",
    }


@pytest.fixture
def task_args():
    """Minimum task args for db create_task for testing."""
    return {
        "queue_name": "test_queue",
        "task_name": "test_task",
        "args": {"param1": 1},
        "metadata": {"tag": "test"},
    }


@pytest.fixture
def db_fixture(request, mock_db, real_db):
    """
    Dynamic database fixture that supports both mock and real databases.
    """
    if request.param == "mock":
        return mock_db
    elif request.param == "real":
        return real_db
    else:
        raise ValueError(f"Unknown database type: {request.param}")
