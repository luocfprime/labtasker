from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlsplit, urlunsplit

from labtasker.errors import ConfigError
from labtasker.local import LocalPaths, local_paths, require_local_capabilities
from labtasker.validation import RequestValidationError, invalid_config, validate_identifier

DEFAULT_QUEUE = "default"
CONFIG_FIELDS = {"url", "queue", "token"}


class EndpointRecord(TypedDict):
    mode: Literal["http", "local"]
    url: str | None
    socket: str | None
    directory: str | None
    database: str | None


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    url: str | None
    queue: str
    token: str | None
    local: LocalPaths | None

    def public_dict(self) -> dict[str, object]:
        return {
            "mode": "local" if self.local is not None else "http",
            "directory": str(self.local.directory) if self.local is not None else None,
            "database": str(self.local.database) if self.local is not None else None,
            "socket": str(self.local.socket) if self.local is not None else None,
            "url": self.url,
            "queue": self.queue,
            "token_configured": self.token is not None,
        }

    def endpoint_dict(self) -> EndpointRecord:
        return {
            "mode": "local" if self.local is not None else "http",
            "url": self.url,
            "socket": str(self.local.socket) if self.local is not None else None,
            "directory": str(self.local.directory) if self.local is not None else None,
            "database": str(self.local.database) if self.local is not None else None,
        }


def resolve_config(
    *,
    url: str | None = None,
    token: str | None = None,
    queue: str | None = None,
    cwd: Path | None = None,
    environment: dict[str, str] | None = None,
) -> ResolvedConfig:
    working_directory = Path.cwd() if cwd is None else cwd
    environment_values = os.environ if environment is None else environment
    file_values = _read_config_file(working_directory)
    constructor_values = {"url": url, "token": token, "queue": queue}
    environment_fields = {
        "url": environment_values.get("LABTASKER_URL"),
        "token": environment_values.get("LABTASKER_TOKEN"),
        "queue": environment_values.get("LABTASKER_QUEUE"),
    }
    defaults: dict[str, str | None] = {
        "url": None,
        "token": None,
        "queue": DEFAULT_QUEUE,
    }

    effective: dict[str, str | None] = {}
    sources: dict[str, str] = {}
    config_path = str(working_directory / ".labtasker" / "config.toml")
    for field in ("url", "token", "queue"):
        candidates = [
            (constructor_values[field], "constructor"),
            (environment_fields[field], "environment"),
            (file_values.get(field), config_path),
            (defaults[field], "default"),
        ]
        selected = next(
            ((candidate, source) for candidate, source in candidates if candidate is not None),
            (None, "default"),
        )
        value, source = selected
        effective[field] = value
        sources[field] = source

    effective_url = _validate_url(effective["url"], source=sources["url"])
    effective_queue = _validate_queue(effective["queue"], source=sources["queue"])
    effective_token = _validate_token(effective["token"], source=sources["token"])
    local: LocalPaths | None = None
    if effective_url is None:
        if effective_token is not None:
            raise invalid_config(
                "A token requires an explicit URL; local mode does not use authentication.",
                source=sources["token"],
                field="token",
            )
        require_local_capabilities()
        local = local_paths(working_directory)
    return ResolvedConfig(
        url=effective_url,
        queue=effective_queue,
        token=effective_token,
        local=local,
    )


def _read_config_file(cwd: Path) -> dict[str, str]:
    config_path = cwd / ".labtasker" / "config.toml"
    legacy_path = cwd / ".labtasker" / "client.toml"
    if not config_path.exists():
        if legacy_path.exists():
            raise ConfigError(
                "legacy_config_found",
                "A v1 client.toml was found; create the v2 flat config.toml manually.",
                {"source": str(legacy_path)},
            )
        return {}
    try:
        raw = config_path.read_bytes()
        parsed = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise invalid_config(
            "The client configuration file could not be read or parsed.",
            source=str(config_path),
        ) from error
    if set(parsed) - CONFIG_FIELDS:
        raise invalid_config(
            f"Unknown configuration keys: {sorted(set(parsed) - CONFIG_FIELDS)!r}.",
            source=str(config_path),
        )
    values: dict[str, str] = {}
    for field, value in parsed.items():
        if not isinstance(value, str) or not value:
            raise invalid_config(
                f"Configuration field '{field}' must be a non-empty string.",
                source=str(config_path),
                field=field,
            )
        values[field] = value
    return values


def _validate_url(value: str | None, *, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise invalid_config("URL must be a non-empty string.", source=source, field="url")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise invalid_config("URL is invalid.", source=source, field="url") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise invalid_config(
            "URL must be an absolute HTTP(S) base URL without userinfo, query or fragment.",
            source=source,
            field="url",
        )
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _validate_queue(value: str | None, *, source: str) -> str:
    try:
        return validate_identifier(value, field="queue")
    except RequestValidationError as error:
        raise invalid_config(str(error), source=source, field="queue") from error


def _validate_token(value: str | None, *, source: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise invalid_config("Token must be a non-empty string.", source=source, field="token")
    return value
