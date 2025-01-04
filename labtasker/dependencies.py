"""Shared dependencies."""

from fastapi import Depends, HTTPException, Request, Security
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
        request.app.state.db = DatabaseClient(config.mongodb_uri, config.db_name)
    return request.app.state.db


async def verify_queue_auth(
    credentials: HTTPBasicCredentials = Security(http_basic),
    db: DatabaseClient = Depends(get_db),
) -> str:
    """Verify queue authentication."""
    try:
        security.authenticate_queue(credentials.username, credentials.password, db)
        return credentials.username
    except HTTPException:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
