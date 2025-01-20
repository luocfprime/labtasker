import base64
from typing import Dict

from passlib.context import CryptContext
from pydantic import SecretStr

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    default="pbkdf2_sha256",
)


def hash_password(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def verify_password(to_be_verified_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(to_be_verified_password, hashed_password)


def get_auth_headers(username: str, password: SecretStr) -> Dict[str, str]:
    """Create Basic Auth headers."""
    auth = f"{username}:{password.get_secret_value()}"
    return {"Authorization": f"Basic {base64.b64encode(auth.encode()).decode()}"}
