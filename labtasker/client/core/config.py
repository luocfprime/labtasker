from collections.abc import Callable
from functools import wraps
from pathlib import Path
from shutil import copytree
from typing import Dict, List, Optional

import tomlkit
import typer
from packaging.utils import canonicalize_name
from pydantic import Field, HttpUrl, SecretStr, model_validator, validate_call
from pydantic_settings import BaseSettings, SettingsConfigDict

from labtasker.client.core.logging import logger, stderr_console
from labtasker.client.core.paths import (
    get_labtasker_client_config_path,
    get_labtasker_root,
    get_template_dir,
)
from labtasker.filtering import register_sensitive_text
from labtasker.security import get_auth_headers


class PluginConfig(BaseSettings):
    default: str = Field(default="all", pattern=r"^(all|selected)$")

    # if default is "all", loaded = all - excluded
    # if default is "selected", loaded = selected
    exclude: List[str] = Field(default_factory=list)
    include: List[str] = Field(default_factory=list)

    # plugin specific configs
    configs: Dict[str, dict] = Field(default_factory=dict)

    @model_validator(mode="before")
    def canonicalize_plugin_names(cls, values):
        """Standardize the keys of the `configs` dictionary using `canonicalize_name`."""
        if "configs" in values and isinstance(values["configs"], dict):
            values["configs"] = {
                canonicalize_name(key, validate=True): value
                for key, value in values["configs"].items()
            }
        return values


class ClientConfig(BaseSettings):
    # API settings
    api_base_url: HttpUrl

    queue_name: str = Field(
        ...,
        pattern=r"^[a-zA-Z0-9_-]+$",
        min_length=1,
        max_length=100,
    )

    password: SecretStr = Field(..., min_length=1, max_length=100)

    heartbeat_interval: float = 30.0  # seconds

    cli_plugins: PluginConfig = Field(default_factory=PluginConfig)

    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="allow",
    )


_config: Optional[ClientConfig] = None


def requires_client_config(
    func: Optional[Callable] = None, /, *, auto_load_config: bool = True
):
    def decorator(function: Callable):
        @wraps(function)
        def wrapped(*args, **kwargs):
            if not _config and not get_labtasker_client_config_path().exists():
                stderr_console.print(
                    f"Configuration not initialized. "
                    f"Run [orange1]`labtasker config`[/orange1] to initialize configuration."
                )
                raise typer.Exit(-1)

            if auto_load_config:
                load_client_config()

            return function(*args, **kwargs)

        return wrapped

    if func is None:
        return decorator

    return decorator(func)


def load_client_config(
    toml_file: Optional[Path] = None,
    skip_if_loaded: bool = True,
    disable_warning: bool = False,
    **overwrite_fields,
):
    if toml_file is None:
        toml_file = get_labtasker_client_config_path()

    global _config
    if _config is not None:
        if skip_if_loaded:
            return
        if not disable_warning:
            logger.warning(
                "ClientConfig already initialized. This would result in a second time loading."
            )
    with open(toml_file, "rb") as f:
        _config = ClientConfig.model_validate(tomlkit.load(f))

    if overwrite_fields:
        update_client_config(**overwrite_fields)

    # register sensitive text
    register_sensitive_text(_config.password.get_secret_value())
    register_sensitive_text(
        get_auth_headers(_config.queue_name, _config.password)["Authorization"]
    )


@requires_client_config(auto_load_config=False)
@validate_call
def update_client_config(**kwargs):
    global _config
    new_config = _config.model_copy(update=locals())
    # validate config
    ClientConfig.model_validate(new_config)
    _config = new_config


@requires_client_config
def get_client_config() -> ClientConfig:
    """Get singleton instance of ClientConfig."""
    return _config


def init_labtasker_root(
    labtasker_root: Path = get_labtasker_root(), exist_ok: bool = False
):
    labtasker_root_template = get_template_dir() / "labtasker_root"

    if labtasker_root.exists() and not exist_ok:
        raise RuntimeError("Labtasker root directory already exists.")

    copytree(
        src=labtasker_root_template,
        dst=labtasker_root,
        dirs_exist_ok=True,
    )
