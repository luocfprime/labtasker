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
        if effective_token == "":
            raise ValueError("LABTASKER_SERVER_TOKEN must not be empty.")
        if not 1 <= port <= 65535:
            raise ValueError("port must be between 1 and 65535.")
        if effective_token is None and not _is_tokenless_host_allowed(host):
            raise ValueError("A token is required when binding to a non-loopback host.")
        return cls(host=host, port=port, database=Path(database), token=effective_token)


def _is_tokenless_host_allowed(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
