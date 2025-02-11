from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Optional

import typer
from pydantic import HttpUrl, SecretStr, validate_call
from pydantic_settings import BaseSettings, SettingsConfigDict

from labtasker.client.core.constants import (
    get_labtasker_client_config_path,
    get_labtasker_root,
)
from labtasker.client.core.logging import logger, stderr_console
from labtasker.filtering import register_sensitive_text
from labtasker.security import get_auth_headers
from labtasker.utils import get_current_time


class ClientConfig(BaseSettings):
    # API settings
    api_base_url: HttpUrl

    queue_name: str
    password: SecretStr

    heartbeat_interval: int  # seconds

    model_config = SettingsConfigDict(
        env_file=get_labtasker_client_config_path(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )


_config: Optional[ClientConfig] = None


def requires_client_config(func: Callable = None, /, *, auto_load_config: bool = True):
    if func is None:  # if no function is provided, return the decorator
        return lambda f: requires_client_config(
            f, auto_load_config=auto_load_config
        )  # return the decorator

    @wraps(func)
    def wrapped(*args, **kwargs):
        if (
            not get_labtasker_client_config_path().exists()
        ):  # check if config file exists
            stderr_console.print(
                f"Configuration at {get_labtasker_client_config_path()} not found. Run `labtasker config` to initialize configuration."
            )
            raise typer.Exit(-1)
        # load config
        if auto_load_config:
            load_client_config()
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
    env_file: str = get_labtasker_client_config_path(),
    skip_if_loaded: bool = True,
    **overwrite_fields,
):
    global _config
    if _config is not None:
        if skip_if_loaded:
            return
        logger.warning(
            "ClientConfig already initialized. This would result a second time loading."
        )
    _config = ClientConfig(_env_file=env_file)  # noqa

    if overwrite_fields:
        update_client_config(**overwrite_fields)

    # register sensitive text
    register_sensitive_text(_config.password.get_secret_value())
    register_sensitive_text(
        get_auth_headers(_config.queue_name, _config.password)["Authorization"]
    )


@requires_client_config(auto_load_config=False)
@validate_call
def update_client_config(
    api_base_url: Optional[HttpUrl] = None,
    queue_name: Optional[str] = None,
    password: Optional[SecretStr] = None,
    heartbeat_interval: Optional[int] = None,
):
    global _config
    new_config = _config.model_copy(update=locals())
    # validate config
    ClientConfig.model_validate(new_config)
    _config = new_config


@requires_client_config(auto_load_config=False)
def dump_client_config():
    global _config
    # Convert the configuration to a dictionary
    config_dict = _config.model_dump()
    # Ensure the password is stored as a string
    config_dict["password"] = _config.password.get_secret_value()

    # Write the configuration to the specified path in .env format
    with open(get_labtasker_client_config_path(), "w", encoding="utf-8") as f:
        for key, value in config_dict.items():
            f.write(f"{key.upper()}={value}\n")
    logger.info(f"Configuration saved to {get_labtasker_client_config_path()}")


@requires_client_config
def get_client_config() -> ClientConfig:
    """Get singleton instance of ClientConfig."""
    return _config


def gitignore_setup():
    """Setup .gitignore file to ignore labtasker_client_config.env"""
    gitignore_path = Path(get_labtasker_root()) / ".gitignore"

    # Ensure .gitignore exists and check if "*.env" is already present
    if not gitignore_path.exists():
        with open(gitignore_path, mode="a", encoding="utf-8") as f:
            f.write("*.env\n")
            f.write("logs\n")
