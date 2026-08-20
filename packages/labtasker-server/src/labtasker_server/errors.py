from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DomainError(Exception):
    status_code: int
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return self.message


def not_found(code: str, message: str, **details: Any) -> DomainError:
    return DomainError(404, code, message, details)


def conflict(code: str, message: str, **details: Any) -> DomainError:
    return DomainError(409, code, message, details)


def invalid(code: str, message: str, **details: Any) -> DomainError:
    return DomainError(422, code, message, details)
