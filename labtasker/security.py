import secrets
from typing import TYPE_CHECKING, Optional

from fastapi import HTTPException
from passlib.context import CryptContext
from starlette.status import HTTP_401_UNAUTHORIZED

if TYPE_CHECKING:
    from .database import DatabaseClient

# Configure password hashing with bcrypt
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    # Configure bcrypt parameters
    bcrypt__rounds=12,  # Work factor (higher = more secure but slower)
    bcrypt__ident="2b",  # Use the strongest version of bcrypt
    # Let bcrypt handle salt internally (it always uses 22 characters)
)


class SecurityManager:
    def __init__(self, pepper: Optional[str] = None):
        """Initialize security manager.

        Args:
            pepper: Optional server-side secret to add to passwords before hashing.
                   This adds an extra layer of security beyond the salt.
        """
        self.pwd_context = pwd_context
        self.pepper = pepper or secrets.token_urlsafe(32)

    def hash_password(self, password: str) -> str:
        """Hash a password with salt and pepper.

        The bcrypt algorithm automatically handles salt generation and storage.
        We add the pepper before hashing for additional security.

        Args:
            password: The password to hash

        Returns:
            str: The hashed password

        Raises:
            ValueError: If password is too short
        """
        # Check password length
        from .config import ServerConfig

        config = ServerConfig()
        if len(password) < config.security_min_password_length:
            raise ValueError(
                f"Password must be at least {config.security_min_password_length} characters long"  # noqa: E501
            )

        if self.pepper:
            password = f"{self.pepper}${password}"
        return self.pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash.

        Args:
            plain_password: The password to verify
            hashed_password: The hashed password from the database

        Returns:
            bool: True if password matches, False otherwise
        """
        if self.pepper:
            plain_password = f"{self.pepper}${plain_password}"
        return self.pwd_context.verify(plain_password, hashed_password)

    def authenticate_queue(
        self, queue_name: str, password: str, db: "DatabaseClient"
    ) -> bool:
        """Authenticate queue access."""
        queue = db._queues.find_one({"queue_name": queue_name})
        if not queue:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Queue not found",
            )
        if not self.verify_password(password, queue["password"]):
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid password",
            )
        return True
