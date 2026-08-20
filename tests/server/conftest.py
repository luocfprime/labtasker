from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from labtasker_server.app import create_app
from labtasker_server.config import ServerSettings


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "server.db"


@pytest.fixture
def app(database_path: Path) -> FastAPI:
    return create_app(ServerSettings(database=database_path))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
