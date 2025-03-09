from datetime import datetime, timedelta

import pytest

from labtasker.client.core.version_checker import (
    check_pypi_status,
    get_last_version_check_path,
    should_check,
)

pytestmark = [pytest.mark.unit]


@pytest.fixture
def patch_yanked_version(monkeypatch):
    monkeypatch.setattr(
        "labtasker.client.core.version_checker.__version__",
        "v0.1.0",  # a known yanked version
    )


@pytest.fixture
def patch_checked(monkeypatch):
    monkeypatch.setattr("labtasker.client.core.version_checker._process_checked", False)


def test_yanked_version_warning(patch_yanked_version, capsys):
    print("test_yanked_version_warning")
    check_pypi_status(force_check=True, blocking=True)
    out, err = capsys.readouterr()
    assert "yanked" in err, (out, err)


def test_multiple_calls(patch_yanked_version, capsys):
    """When called multiple times, only display once"""
    check_pypi_status(force_check=True, blocking=False)
    # the second call should wait until the first one is done
    check_pypi_status(blocking=True)
    out, err = capsys.readouterr()
    # assert "yanked" only appeared once
    assert err.count("yanked") == 1, (out, err)


def test_check_once_per_day(
    monkeypatch, patch_yanked_version, labtasker_test_root, capsys
):
    assert not get_last_version_check_path().exists()
    check_pypi_status(force_check=True, blocking=True)
    # after the first call, the file should exist
    assert get_last_version_check_path().exists()

    last_checked_time = datetime.fromisoformat(
        get_last_version_check_path().read_text().strip()
    )
    assert datetime.now() - last_checked_time < timedelta(
        minutes=1
    ), "Should be very recently checked."

    # temporarily change the last checked time to be 1 day ago
    # and patch the _process_checked to False, see if now should_check()
    monkeypatch.setattr("labtasker.client.core.version_checker._process_checked", False)
    assert not should_check()
    get_last_version_check_path().write_text(
        (datetime.now() - timedelta(days=1, hours=1)).isoformat()
    )
    assert should_check()
