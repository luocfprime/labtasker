from datetime import datetime, timedelta, timezone

import pytest

from labtasker.server.database import get_current_time as db_get_current_time
from labtasker.utils import get_current_time as utils_get_current_time
from tests.fixtures.mock_datetime_now import mock_get_current_time


@pytest.mark.unit
@pytest.mark.parametrize(
    "get_current_time_fn", [utils_get_current_time, db_get_current_time]
)
def test_mock_get_current_time(mock_get_current_time, get_current_time_fn):
    # Initial mocked time should match the fixture's initial time
    initial_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    mock_get_current_time.set_current_time(initial_time)

    mock_time = get_current_time_fn()
    assert mock_time == initial_time, f"mock_time={mock_time}"

    # Advance time and verify get_current_time returns the new time
    mock_get_current_time.tick(timedelta(hours=1))
    expected_time = initial_time + timedelta(hours=1)
    assert get_current_time_fn() == expected_time

    # Try with missing timezone info
    initial_time = datetime(2025, 1, 1, 12, 0, 0)
    mock_get_current_time.set_current_time(initial_time)
    assert get_current_time_fn() == initial_time.astimezone(
        tz=None
    )  # get_current_time_fn() default to local timezone

    # Try change a timezone
    assert get_current_time_fn(
        tz=timezone(timedelta(hours=8))
    ) == initial_time.astimezone(timezone(timedelta(hours=8)))
