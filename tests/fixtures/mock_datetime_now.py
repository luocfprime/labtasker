from datetime import datetime, timedelta

import pytest
from black import timezone


class TimeControl:
    """Helper class for controlling time in tests."""

    def __init__(self, current_time: datetime):
        self._current_time = current_time

    def set_current_time(self, current_time: datetime):
        self._current_time = current_time

    def current_time(self, tz) -> datetime:
        return self._current_time.astimezone(tz)

    def tick(self, delta: timedelta) -> datetime:
        self._current_time += delta
        return self._current_time


@pytest.fixture
def mock_get_current_time(monkeypatch):
    """Fixture to mock labtasker.utils.get_current_time with controllable current time."""
    # Start with a fixed time to make tests deterministic
    time_control = TimeControl(
        current_time=datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    )

    # Patch get_current_time in all modules that use it
    def mock_get_current_time(tz=timezone.utc):
        return time_control.current_time(tz)

    monkeypatch.setattr("labtasker.utils._get_current_time", mock_get_current_time)

    return time_control
