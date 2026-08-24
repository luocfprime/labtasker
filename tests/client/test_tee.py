from __future__ import annotations

import logging

from labtasker.tee import _worker_log_formatter


def test_default_worker_log_format_has_utc_timestamp_level_and_component() -> None:
    record = logging.LogRecord(
        name="labtasker.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Worker idle timeout reached; stopping normally.",
        args=(),
        exc_info=None,
    )
    record.created = 1_777_032_000.123
    record.msecs = 123.0

    assert _worker_log_formatter().format(record) == (
        "2026-04-24T12:00:00.123Z INFO [labtasker] Worker idle timeout reached; stopping normally."
    )
