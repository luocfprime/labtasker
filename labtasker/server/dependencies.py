"""Shared dependencies."""

from typing import Any, Mapping

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED

from labtasker.security import verify_password
from labtasker.server.config import ServerConfig
from labtasker.server.database import DBService

http_basic = HTTPBasic()


def get_server_config() -> ServerConfig:
    """Get server configuration singleton."""
    if not ServerConfig._instance:
        raise RuntimeError("Server configuration not initialized properly.")
    return ServerConfig._instance


def get_db(request: Request) -> DBService:
    """Database dependency."""
    if not hasattr(request.app.state, "db"):
        raise RuntimeError(
            "Database not initialized. Application must be started with proper lifespan context."
        )
    return request.app.state.db


async def get_verified_queue_dependency(
    credentials: HTTPBasicCredentials = Security(http_basic),
    db: DBService = Depends(get_db),
) -> Mapping[str, Any]:
    """Verify queue authentication using HTTP Basic Auth.

    Uses queue_name as username and password for authentication.
    """
    try:
        queue = db.get_queue(queue_name=credentials.username)
        if not verify_password(credentials.password, queue["password"]):
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic"},
            )
        return queue
    except Exception as e:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
