import time

import pytest
from pymongo import MongoClient as RealMongoClient

from labtasker.server.database import DBService

_real_db_instance = None  # keeps session scoped singleton


def is_mongo_ready(uri):
    """
    Check if the MongoDB service is ready by running a 'ping' command.
    """
    try:
        client = RealMongoClient(uri, serverSelectionTimeoutMS=1000)
        return client.admin.command("ping")["ok"] != 0.0
    except Exception:
        return False


@pytest.fixture
def real_db(request, server_config):
    """
    MongoDB factory used for fixture lazy loading.
    """
    global _real_db_instance

    if not _real_db_instance:
        # Lazy load docker services
        docker_services = request.getfixturevalue("docker_services")
        docker_ip = request.getfixturevalue("docker_ip")

        port = docker_services.port_for("mongodb", 27017)
        host = docker_ip

        username = server_config.db_user
        password = server_config.db_password

        uri = f"mongodb://{username}:{password}@{host}:{port}/?authSource=admin&directConnection=true&replicaSet=rs0"

        # Wait for MongoDB to be ready
        docker_services.wait_until_responsive(
            check=lambda: is_mongo_ready(uri),
            timeout=30.0,  # Wait up to 30 seconds
            pause=1.0,  # Check every 1 seconds
        )

        time.sleep(5)  # wait for the docker/mongodb/post-init.d script to be executed

        # Create a DatabaseClient object
        _real_db_instance = DBService(db_name=server_config.db_name, uri=uri)

    yield _real_db_instance

    _real_db_instance.erase()  # clean up
