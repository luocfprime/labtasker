from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8000
    database: Path = Path(".labtasker/server.db")
    token: str | None = None
    database_fd: int | None = None

    def __post_init__(self) -> None:
        _validate_token(self.token)

    @classmethod
    def from_values(
        cls,
        *,
        host: str = "127.0.0.1",
        port: int = 8000,
        database: str | Path = ".labtasker/server.db",
        token: str | None = None,
    ) -> ServerSettings:
        effective_token = os.environ.get("LABTASKER_SERVER_TOKEN") if token is None else token
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535.")
        if effective_token is None and not _is_tokenless_host_allowed(host):
            raise ValueError("A token is required when binding to a non-loopback host.")
        return cls(host=host, port=port, database=Path(database), token=effective_token)


def _validate_token(token: str | None) -> None:
    if token is not None and not isinstance(token, str):
        raise ValueError("LABTASKER_SERVER_TOKEN must be a string.")
    if token == "":
        raise ValueError("LABTASKER_SERVER_TOKEN must not be empty.")
    if token is not None and any(not 0x21 <= ord(character) <= 0x7E for character in token):
        raise ValueError("LABTASKER_SERVER_TOKEN must contain only visible ASCII characters.")


def _is_tokenless_host_allowed(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
