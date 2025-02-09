import sys
from contextlib import contextmanager
from typing import Set

from fastapi.exceptions import HTTPException

_registered_sensitive_texts: Set[str] = set()
_hook_enabled = True


def register_sensitive_text(text: str):
    """Register a sensitive text to be filtered out of tracebacks"""
    _registered_sensitive_texts.add(text)


def sanitize_text(text: str):
    for sensitive_text in _registered_sensitive_texts:
        text = text.replace(sensitive_text, "*" * len(sensitive_text))
    return text


def sanitize_exception_chain(exc):
    """
    Recursively sanitize exception messages in the exception chain, including
    __cause__ and __context__.
    """
    if exc is None:
        return None

    # Sanitize the current exception message
    sanitized_msg = sanitize_text(str(exc))
    sanitized_exc = type(exc)(sanitized_msg)

    # Recursively sanitize __cause__ and __context__
    sanitized_exc.__cause__ = sanitize_exception_chain(exc.__cause__)
    sanitized_exc.__context__ = sanitize_exception_chain(exc.__context__)

    return sanitized_exc


def install_traceback_filter():
    """Install a system-wide traceback filter for sensitive information"""
    original_excepthook = sys.excepthook

    def filtered_excepthook(exc_type, exc_value, exc_tb):
        if not _hook_enabled:
            original_excepthook(exc_type, exc_value, exc_tb)
            return

        sanitized_msg = sanitize_text(str(exc_value) if exc_value else "")

        if issubclass(exc_type, HTTPException):
            # preserve http status code
            sanitized_exc = HTTPException(
                status_code=(
                    exc_value.status_code if hasattr(exc_value, "status_code") else 500
                ),
                detail=sanitized_msg,
                headers=getattr(exc_value, "headers", None),
            )
        else:
            sanitized_exc = exc_type(sanitized_msg)

        original_excepthook(exc_type, sanitized_exc, exc_tb)

    sys.excepthook = filtered_excepthook


@contextmanager
def filter_exception():
    try:
        yield
    except Exception as e:
        sanitized_exc = sanitize_exception_chain(e)

        # Raise the sanitized exception without retaining the original chain
        raise sanitized_exc from None


def set_traceback_filter_hook(enabled: bool = True):
    global _hook_enabled
    _hook_enabled = enabled
