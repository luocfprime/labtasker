"""Shared dependencies."""

from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED

from .config import ServerConfig
from .database import DatabaseClient
from .security import SecurityManager

config = ServerConfig()
security = SecurityManager(pepper=config.security_pepper)
http_basic = HTTPBasic()


def get_db(request: Request) -> DatabaseClient:
    """Database dependency."""
    if not hasattr(request.app.state, "db"):
        raise RuntimeError(
            "Database not initialized. Application must be started with proper lifespan context."
        )
    return request.app.state.db


async def get_verified_queue_dependency(
    credentials: HTTPBasicCredentials = Security(http_basic),
    db: DatabaseClient = Depends(get_db),
) -> Dict[str, Any]:
    """Verify queue authentication using HTTP Basic Auth.

    Uses queue_name as username and password for authentication.
    """
    try:
        queue = db.get_queue(queue_name=credentials.username)
        if not db.security.verify_password(credentials.password, queue["password"]):
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
                headers={"WWW-Authenticate": "Basic"},
            )
        return queue
    except Exception as e:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
