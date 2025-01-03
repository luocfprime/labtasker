import os
from typing import Optional

from dotenv import load_dotenv


class ServerConfig:
    def __init__(self, env_file: Optional[str] = None):
        if env_file:
            load_dotenv(env_file)

        # Database settings
        self.db_user = os.getenv("DB_USER")
        self.db_password = os.getenv("DB_PASSWORD")
        self.db_name = os.getenv("DB_NAME", "labtasker_db")
        self.db_host = os.getenv("DB_HOST", "localhost")
        self.db_port = int(os.getenv("DB_PORT", "27017"))

        # Admin settings
        self.admin_username = os.getenv("ADMIN_USERNAME", "labtasker")
        self.admin_password = os.getenv("ADMIN_PASSWORD")

        # API settings
        self.api_host = os.getenv("API_HOST", "0.0.0.0")
        self.api_port = int(os.getenv("API_PORT", "8080"))

        # Security settings
        self.security_pepper = os.getenv("SECURITY_PEPPER")
        self.security_bcrypt_rounds = int(os.getenv("SECURITY_BCRYPT_ROUNDS", "12"))
        self.security_min_password_length = int(
            os.getenv("SECURITY_MIN_PASSWORD_LENGTH", "12")
        )
        self.security_max_login_attempts = int(
            os.getenv("SECURITY_MAX_LOGIN_ATTEMPTS", "5")
        )
        self.security_lockout_duration = int(
            os.getenv("SECURITY_LOCKOUT_DURATION", "15")
        )

        # Validate security settings
        if self.security_bcrypt_rounds < 10:
            raise ValueError("SECURITY_BCRYPT_ROUNDS must be at least 10")
        if self.security_min_password_length < 8:
            raise ValueError("SECURITY_MIN_PASSWORD_LENGTH must be at least 8")

    @property
    def mongodb_uri(self) -> str:
        """Get MongoDB URI from config."""
        if self.db_user and self.db_password:
            return f"mongodb://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}"
        return f"mongodb://{self.db_host}:{self.db_port}"
