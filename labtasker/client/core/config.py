from functools import wraps
from typing import Optional

from pydantic import HttpUrl, SecretStr, validate_call
from pydantic_settings import BaseSettings, SettingsConfigDict

from labtasker.client.core.logging import logger
from labtasker.constants import LABTASKER_CLIENT_CONFIG_PATH, LABTASKER_ROOT
from labtasker.utils import get_current_time


class ClientConfig(BaseSettings):
    # API settings
    api_base_url: HttpUrl

    queue_name: str
    password: SecretStr

    heartbeat_interval: int  # seconds

    model_config = SettingsConfigDict(
        env_file=LABTASKER_CLIENT_CONFIG_PATH,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )


_config: Optional[ClientConfig] = None


def requires_client_config(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        if _config is None:
            raise RuntimeError("ClientConfig not initialized.")
        return func(*args, **kwargs)

    return wrapped


def init_config_with_default():
    global _config
    if _config:
        logger.warning(
            "ClientConfig already initialized. Initializing again with default would overwrite existing values. Please check if this is intended."
        )
    _config = ClientConfig(
        api_base_url=HttpUrl("http://localhost:8080"),
        queue_name=f"queue-{get_current_time().strftime('%Y-%m-%d-%H-%M-%S')}",
        password=SecretStr("my-secret"),
        heartbeat_interval=30,
    )


def load_client_config(
    env_file: str = LABTASKER_CLIENT_CONFIG_PATH, **overwrite_fields
):
    global _config
    if _config is not None:
        logger.warning(
            "ClientConfig already initialized. This would result a second time loading."
        )
    _config = ClientConfig(_env_file=env_file)  # noqa

    if overwrite_fields:
        update_client_config(**overwrite_fields)


@requires_client_config
@validate_call
def update_client_config(
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
    # Convert the configuration to a dictionary
    config_dict = _config.model_dump()
    # Ensure the password is stored as a string
    config_dict["password"] = _config.password.get_secret_value()

    # Write the configuration to the specified path in .env format
    with open(LABTASKER_CLIENT_CONFIG_PATH, "w", encoding="utf-8") as f:
        for key, value in config_dict.items():
            f.write(f"{key.upper()}={value}\n")
    logger.info(f"Configuration saved to {LABTASKER_CLIENT_CONFIG_PATH}")


@requires_client_config
def get_client_config() -> ClientConfig:
    """Get singleton instance of ClientConfig."""
    return _config


from pathlib import Path


def gitignore_setup():
    """Setup .gitignore file to ignore labtasker_client_config.env"""
    gitignore_path = Path(LABTASKER_ROOT) / ".gitignore"

    # Ensure .gitignore exists and check if "*.env" is already present
    if not gitignore_path.exists():
        with open(gitignore_path, mode="a", encoding="utf-8") as f:
            f.write("*.env\n")
            f.write("logs\n")
