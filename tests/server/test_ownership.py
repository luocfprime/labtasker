from __future__ import annotations

import os
from pathlib import Path

import pytest

from labtasker_server import ownership


def test_runtime_directory_preserves_leaf_for_symlink_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    effective_uid = os.geteuid() if hasattr(os, "geteuid") else os.getuid()
    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    leaf = tmp_path / f"labtasker-{effective_uid}"
    leaf.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(ownership, "RUNTIME_PARENT", tmp_path)

    assert ownership.runtime_directory() == leaf
    with pytest.raises(RuntimeError, match="Runtime directory must be owner-only"):
        ownership.ensure_runtime_directory()
    with pytest.raises(RuntimeError, match="Runtime directory must be owner-only"):
        ownership.sidecar_is_locked("db", tmp_path / "server.db")
    assert not any(target.iterdir())
