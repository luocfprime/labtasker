from __future__ import annotations

from pathlib import Path

import pytest

from labtasker_server import filesystem


@pytest.mark.parametrize(
    ("filesystem_type", "classification", "effective", "warns"),
    [
        ("ext4", "local", "local", False),
        ("nfs4", "shared", "shared", False),
        ("wekafs", "shared", "shared", False),
        ("lustre", "shared", "shared", False),
        ("futurefs", "unknown", "shared", True),
    ],
)
def test_auto_database_filesystem_is_conservative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filesystem_type: str,
    classification: str,
    effective: str,
    warns: bool,
) -> None:
    monkeypatch.setattr(filesystem, "_filesystem_type", lambda _: filesystem_type)
    result = filesystem.resolve_database_filesystem(tmp_path / "missing/server.db", "auto")
    assert result.detection is not None
    assert result.detection.classification == classification
    assert result.effective == effective
    assert (result.warning is not None) is warns
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("requested", ["local", "shared"])
def test_explicit_database_filesystem_bypasses_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
) -> None:
    def fail(_: Path) -> str:
        raise AssertionError("detection must not run")

    monkeypatch.setattr(filesystem, "_filesystem_type", fail)
    result = filesystem.resolve_database_filesystem(
        tmp_path / "server.db",
        requested,  # type: ignore[arg-type]
    )
    assert result.effective == requested
    assert result.detection is None
    assert result.warning is None
