import os
import sys
from contextlib import contextmanager
from types import TracebackType
from typing import Optional, Set, Type

from rich.traceback import Traceback
from typer.main import console_stderr

_registered_sensitive_texts: Set[str] = set()
_hook_enabled = True


def register_sensitive_text(text: str):
    """Register a sensitive text to be filtered out of tracebacks"""
    _registered_sensitive_texts.add(text)


def sanitize_text(text: str):
    for sensitive_text in _registered_sensitive_texts:
        text = text.replace(sensitive_text, "*" * len(sensitive_text))
    return text


def sanitize_single_exception(exc_value):
    # Sanitize sensitive information in exception args
    sanitized_args = [
        sanitize_text(arg) if isinstance(arg, str) else arg for arg in exc_value.args
    ]

    exc_value.args = tuple(sanitized_args)

    # Sanitize sensitive information in exception strings
    for k, v in getattr(exc_value, "__dict__", {}).items():
        if isinstance(v, str):
            setattr(exc_value, k, sanitize_text(v))

    return exc_value


def sanitize_exception_chain(exc):
    """
    Recursively sanitize exception messages in the exception chain, including
    __cause__ and __context__.
    """
    if exc is None:
        return None

    # Sanitize the current exception message
    sanitized_exc = sanitize_single_exception(exc)

    # Recursively sanitize __cause__ and __context__
    sanitized_exc.__cause__ = sanitize_exception_chain(exc.__cause__)
    sanitized_exc.__context__ = sanitize_exception_chain(exc.__context__)

    return sanitized_exc


def install_traceback_filter():
    """Install a system-wide traceback filter with rich pretty-print support."""
    original_excepthook = sys.excepthook

    def filtered_excepthook(
        exc_type: Type[BaseException],
        exc_value: BaseException,
        exc_tb: Optional[TracebackType],
    ) -> None:
        if not _hook_enabled:
            original_excepthook(exc_type, exc_value, exc_tb)
            return

        sanitized_exc = sanitize_exception_chain(exc_value)

        # If the sanitized exception still contains sensitive content, print a warning and return
        if sanitized_exc.__str__() != sanitize_text(
            sanitized_exc.__str__()
        ) or sanitized_exc.__repr__() != sanitize_text(sanitized_exc.__repr__()):
            console_stderr.print(
                "[bold orange1]Warning:[/bold orange1] Trackback sensitive content filtering failed. Traceback is intercepted and omitted from printing."
            )
            return

        # Paths to suppress from traceback output
        suppress_internal_dir_names = [
            os.path.dirname(__file__),
        ]

        # Use rich traceback for pretty output
        rich_tb = Traceback.from_exception(
            type(sanitized_exc),
            sanitized_exc,
            exc_tb,
            show_locals=False,  # Do not show locals
            suppress=suppress_internal_dir_names,
            width=80,  # Set a default width
        )
        console_stderr.print(rich_tb)

    # Install the custom excepthook
    sys.excepthook = filtered_excepthook


@contextmanager
def filter_exception():
    """Remove the old exception chain, filters sensitive content."""
    try:
        yield
    except Exception as e:
        sanitized_exc = sanitize_exception_chain(e)

        # Raise the sanitized exception without retaining the original chain
        raise sanitized_exc from None


def set_traceback_filter_hook(enabled: bool = True):
    global _hook_enabled
    _hook_enabled = enabled
