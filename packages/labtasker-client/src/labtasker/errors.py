from __future__ import annotations

from typing import Any


class LabtaskerError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = {} if details is None else details

    def as_envelope(self) -> dict[str, object]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            }
        }


class ConfigError(LabtaskerError):
    def __init__(self, code: str, message: str, details: dict[str, Any]) -> None:
        if code not in {"invalid_config", "legacy_config_found"}:
            raise ValueError(f"Unsupported ConfigError code: {code}")
        super().__init__(code, message, details)


class TransportError(LabtaskerError):
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__("transport_error", message, details)


class APIError(LabtaskerError):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any],
    ) -> None:
        super().__init__(code, message, details)
        self.status_code = status_code


class TransientError(Exception):
    """Return the current Task to pending without charging this incident."""


class TaskError(Exception):
    """Fail the current execution and continue the Worker loop."""


class FatalWorkerError(Exception):
    """Fail the current execution and stop the Worker process."""
