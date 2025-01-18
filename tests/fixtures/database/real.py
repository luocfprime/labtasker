import time

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

from labtasker.server.database import AsyncDBService

_real_db_client = None  # keeps session scoped client


async def is_mongo_ready(uri):
    """
    Check if the MongoDB service is ready by running a 'ping' command.
    """
    try:
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=1000)
        await client.admin.command("ping")
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def real_db_client(request):
    """Session-scoped fixture for database client initialization."""
    global _real_db_client

    if not _real_db_client:
        # Lazy load docker services
        docker_services = request.getfixturevalue("docker_services")
        docker_ip = request.getfixturevalue("docker_ip")

        port = docker_services.port_for("mongodb", 27017)
        host = docker_ip
        username = "test_user"
        password = "test_password"

        uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource=admin&directConnection=true&replicaSet=rs0"

        # Wait for MongoDB to be ready
        docker_services.wait_until_responsive(
            check=lambda: is_mongo_ready(uri),
            timeout=30.0,  # Wait up to 30 seconds
            pause=1.0,  # Check every 1 seconds
        )

        # Connect to MongoDB using the connection details
        _real_db_client = AsyncIOMotorClient(
            uri,
            w="majority",
            retryWrites=True,
        )

        time.sleep(5)  # wait for the docker/mongodb/post-init.d script to be executed

    return _real_db_client


@pytest.fixture
async def real_db(real_db_client):
    """
    MongoDB fixture that uses the session-scoped client.
    """
    # Create a AsyncDBService object using the shared client
    db = await AsyncDBService.init(client=real_db_client, db_name="test_db")

    yield db

    await db.erase()  # clean up after each test
