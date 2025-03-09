import pytest

import labtasker
from labtasker.client.core.version_checker import check_pypi_status

pytestmark = [pytest.mark.unit]


@pytest.fixture
def patch_version(monkeypatch):
    monkeypatch.setattr(
        "labtasker.client.core.version_checker.__version__",
        "v0.1.0",  # a known yanked version
    )
    monkeypatch.setattr("labtasker.client.core.version_checker._should_check", True)
    monkeypatch.setattr("labtasker.client.core.version_checker._checked", False)


def test_yanked_version_warning(patch_version, capsys):
    print("test_yanked_version_warning")
    check_pypi_status(blocking=True)
    out, err = capsys.readouterr()
    assert "yanked" in err, (out, err)
