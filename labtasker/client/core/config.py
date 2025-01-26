from functools import wraps
from pathlib import Path
from typing import Optional

from pydantic import HttpUrl, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from labtasker.client.core.logging import logger


class ClientConfig(BaseSettings):
    # API settings
    api_base_url: HttpUrl = "http://localhost:8080"

    queue_name: str
    password: SecretStr

    heartbeat_interval: int = 30  # seconds

    model_config = SettingsConfigDict(
        env_file=".labtasker/client.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )


_config: Optional[ClientConfig] = None
_config_path = Path(".labtasker/client.env")


def requires_client_config(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if _config is None:
            raise RuntimeError("ClientConfig not initialized.")
        return func(*args, **kwargs)

    return wrapped


def load_client_config(env_file: Optional[str] = None, **overwrite_fields):
    global _config
    if _config is not None:
        logger.warning(
            "ClientConfig already initialized. This would result a second time loading."
        )
    _config = ClientConfig(_env_file=env_file)  # noqa

    if overwrite_fields:
        change_client_config(**overwrite_fields)


@requires_client_config
def change_client_config(
    api_base_url: Optional[HttpUrl] = None,
    queue_name: Optional[str] = None,
    password: Optional[SecretStr] = None,
    heartbeat_interval: Optional[int] = None,
):
    global _config
    _config = _config.model_copy(update=locals())


@requires_client_config
def dump_client_config():
    global _config

    # TODO:

    raise NotImplementedError()


@requires_client_config
def get_client_config() -> ClientConfig:
    """Get singleton instance of ClientConfig."""
    return _config


def get_client_config_path() -> Path:
    return _config_path
