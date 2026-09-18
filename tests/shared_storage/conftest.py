from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from labtasker_server.filesystem import detect_filesystem

SHARED_STORAGE_DIRECTORY_ENV = "LABTASKER_SHARED_STORAGE_TEST_DIR"


@pytest.fixture(scope="session")
def shared_storage_root() -> Path:
    configured = os.environ.get(SHARED_STORAGE_DIRECTORY_ENV)
    if configured is None:
        pytest.skip(f"set {SHARED_STORAGE_DIRECTORY_ENV} to a writable shared-filesystem directory")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        pytest.fail(f"{SHARED_STORAGE_DIRECTORY_ENV} is not a directory: {root}")
    detection = detect_filesystem(root)
    if detection.classification == "local":
        pytest.fail(
            f"{SHARED_STORAGE_DIRECTORY_ENV} resolved to known-local filesystem "
            f"{detection.filesystem_type!r} at {detection.inspected_path}; point it at the "
            "actual NFS, WekaFS, Lustre, or comparable shared mount"
        )
    try:
        with tempfile.TemporaryDirectory(prefix="labtasker-write-probe-", dir=root):
            pass
    except OSError as error:
        pytest.fail(f"shared-storage test directory is not writable: {root}: {error}")
    return root


@pytest.fixture
def shared_storage_case(shared_storage_root: Path) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(
        prefix="labtasker-shared-test-", dir=shared_storage_root
    ) as case:
        yield Path(case).resolve()


@pytest.fixture(autouse=True)
def isolated_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "http_proxy",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
