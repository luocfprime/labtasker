"""Shared dependencies."""

from typing import Any, Mapping

from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.status import HTTP_401_UNAUTHORIZED

from labtasker.security import verify_password
from labtasker.server.database import DBService, get_db

http_basic = HTTPBasic()


async def get_verified_queue_dependency(
    credentials: HTTPBasicCredentials = Security(http_basic),
    db: DBService = Depends(get_db),
) -> Mapping[str, Any]:
    """Verify queue authentication using HTTP Basic Auth.

    Uses queue_name as username and password for authentication.
    """
    try:
        queue = db.get_queue(queue_id=credentials.username) or db.get_queue(
            queue_name=credentials.username
        )  # get queue by either id or name
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
