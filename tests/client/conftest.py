from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_client_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    for name in (
        "LABTASKER_URL",
        "LABTASKER_TOKEN",
        "LABTASKER_SOCKET",
        "LABTASKER_LOCAL_DIRECTORY",
        "LABTASKER_QUEUE",
    ):
        monkeypatch.delenv(name, raising=False)
    yield
