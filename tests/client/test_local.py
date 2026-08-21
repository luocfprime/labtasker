from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from labtasker.errors import ConfigError
from labtasker.local import ensure_local_server, local_paths


def test_missing_server_fails_before_creating_local_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = local_paths(tmp_path)
    monkeypatch.setattr("labtasker.local.socket_health", lambda _: False)
    monkeypatch.setattr("labtasker.local.importlib.util.find_spec", lambda _: None)

    with pytest.raises(ConfigError, match="requires labtasker-server"):
        ensure_local_server(paths, emit=lambda _: None)

    assert not (tmp_path / ".labtasker").exists()


def test_client_delegates_startup_to_server_coordinator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = local_paths(tmp_path)
    health = iter((False, True))
    observed: dict[str, object] = {}

    monkeypatch.setattr("labtasker.local.socket_health", lambda _: next(health))
    monkeypatch.setattr("labtasker.local.importlib.util.find_spec", lambda _: object())

    def run(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed["arguments"] = arguments
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            arguments,
            0,
            stdout=('{"ok":true,"started":true,"state":"running","pid":123,"version":"2.0.0"}'),
        )

    monkeypatch.setattr("labtasker.local.subprocess.run", run)
    messages: list[str] = []
    result = ensure_local_server(paths, emit=messages.append)

    assert result.started is True
    assert result.pid == 123
    assert result.server_version == "2.0.0"
    assert observed["arguments"][-3:] == [
        "_ensure-daemon",
        "--directory",
        str(tmp_path),
    ]
    assert observed["cwd"] == tmp_path
    assert messages == [
        f"requesting local daemon ensure directory={tmp_path} socket={paths.socket}"
    ]
