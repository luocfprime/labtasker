from typing import Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServerConfig(BaseSettings):
    # Database settings
    db_user: str
    db_password: str
    db_name: str = "labtasker_db"
    db_host: str = "localhost"
    db_port: int = 27017

    # API settings
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # Other settings
    periodic_task_interval: float = 30.0

    model_config = SettingsConfigDict(
        # env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    @field_validator("db_user", "db_password")
    def validate_required_fields(cls, v, field):
        if not v:
            raise ValueError(f"{field.name} must be set")
        return v

    @property
    def mongodb_uri(self) -> str:
        """Get MongoDB URI from config."""
        return (
            f"mongodb://{self.db_user}:{self.db_password}@"
            f"{self.db_host}:{self.db_port}/"
            "?authSource=admin&directConnection=true&replicaSet=rs0"
        )


_config: Optional[ServerConfig] = None


def init_server_config(env_file: Optional[str] = None):
    global _config
    if _config is not None:
        raise RuntimeError("ServerConfig already initialized.")
    _config = ServerConfig(_env_file=env_file)  # noqa


def get_server_config() -> ServerConfig:
    """Get singleton instance of ServerConfig."""
    if _config is None:
        raise RuntimeError("ServerConfig not initialized.")
    return _config
