from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from labtasker import Client, ConfigError, TransportError

ISOLATED_NAMES = (
    "LABTASKER_URL",
    "LABTASKER_TOKEN",
    "LABTASKER_SOCKET",
    "LABTASKER_ROOT",
    "LABTASKER_QUEUE",
    "LABTASKER_SERVER_TOKEN",
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "http_proxy",
    "https_proxy",
)


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in ISOLATED_NAMES:
        environment.pop(name, None)
    return environment


def _server(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "labtasker_server", *arguments],
        cwd=root.parent,
        env=_environment(),
        check=False,
        capture_output=True,
        text=True,
        timeout=40,
    )


def _status(root: Path) -> dict[str, object]:
    result = _server(root, "status", "--labtasker-root", str(root))
    assert result.returncode == 0, result.stderr
    payload: object = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return {str(key): value for key, value in payload.items()}


def _stop(root: Path) -> None:
    result = _server(root, "stop", "--labtasker-root", str(root), "--force")
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name != "posix", reason="managed local requires POSIX")
def test_default_client_only_connects_and_creates_no_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ISOLATED_NAMES:
        monkeypatch.delenv(name, raising=False)

    with Client() as client, pytest.raises(TransportError) as raised:
        client.list_queues()

    assert raised.value.details["labtasker_root"] == str((tmp_path / ".labtasker").resolve())
    assert any("--auto-start-local-server" in remedy for remedy in raised.value.details["remedies"])
    assert not (tmp_path / ".labtasker").exists()


@pytest.mark.skipif(os.name != "posix", reason="managed local requires POSIX")
def test_authorized_auto_start_is_repeatable_and_creates_no_config(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = (tmp_path / ".labtasker").resolve()
    monkeypatch.chdir(tmp_path)
    for name in ISOLATED_NAMES:
        monkeypatch.delenv(name, raising=False)
    try:
        with Client(auto_start_local_server=True) as first:
            assert [queue.name for queue in first.list_queues()] == ["default"]
        first_status = _status(root)
        with Client(auto_start_local_server=True) as second:
            assert [queue.name for queue in second.list_queues()] == ["default"]
        second_status = _status(root)
        assert first_status["pid"] == second_status["pid"]
        assert second_status["state"] == "running"
        assert (root / "server.db").exists()
        assert not (root / "config.toml").exists()
    finally:
        _stop(root)


@pytest.mark.skipif(os.name != "posix", reason="managed local requires POSIX")
def test_concurrent_authorized_clients_elect_one_daemon(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = (tmp_path / ".labtasker").resolve()
    monkeypatch.chdir(tmp_path)
    for name in ISOLATED_NAMES:
        monkeypatch.delenv(name, raising=False)

    def connect(_: int) -> list[str]:
        with Client(auto_start_local_server=True) as client:
            return [queue.name for queue in client.list_queues()]

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            assert list(executor.map(connect, range(4))) == [["default"]] * 4
        status = _status(root)
        assert status["state"] == "running"
        assert isinstance(status["pid"], int)
    finally:
        _stop(root)


@pytest.mark.skipif(os.name != "posix", reason="daemon management requires POSIX")
def test_explicit_shared_socket_daemon_is_idempotent_and_conflicts_cleanly(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "root").resolve()
    database = tmp_path / "shared.db"
    command = (
        "serve",
        "--connection",
        "socket",
        "--daemon",
        "--labtasker-root",
        str(root),
        "--database",
        str(database),
        "--database-filesystem",
        "shared",
    )
    try:
        first = _server(root, *command)
        assert first.returncode == 0, first.stderr
        pid = _status(root)["pid"]
        repeated = _server(root, *command)
        assert repeated.returncode == 0, repeated.stderr
        assert _status(root)["pid"] == pid

        conflict = _server(
            root,
            "serve",
            "--connection",
            "socket",
            "--daemon",
            "--labtasker-root",
            str(root),
            "--database",
            str(tmp_path / "different.db"),
            "--database-filesystem",
            "shared",
        )
        assert conflict.returncode == 1
        assert "configuration conflicts" in conflict.stderr
        assert "labtasker-server stop" in conflict.stderr
        assert _status(root)["pid"] == pid
    finally:
        _stop(root)


@pytest.mark.skipif(os.name != "posix", reason="daemon management requires POSIX")
def test_http_daemon_readiness_is_bound_to_the_started_child(tmp_path: Path) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    first_root = (tmp_path / "first-root").resolve()
    second_root = (tmp_path / "second-root").resolve()
    arguments = (
        "serve",
        "--connection",
        "http",
        "--daemon",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--database-filesystem",
        "local",
    )
    try:
        first = _server(first_root, *arguments, "--labtasker-root", str(first_root))
        assert first.returncode == 0, first.stderr
        with Client(url=f"http://127.0.0.1:{port}") as client:
            assert [queue.name for queue in client.list_queues()] == ["default"]

        blocked = _server(second_root, *arguments, "--labtasker-root", str(second_root))
        assert blocked.returncode == 1
        assert "listener confirmation" in blocked.stderr
        assert _status(second_root)["state"] == "stopped"
        assert _status(first_root)["state"] == "running"
    finally:
        _stop(second_root)
        _stop(first_root)


def test_explicit_socket_is_external_and_cannot_receive_auto_start_authority(
    tmp_path: Path,
) -> None:
    socket_path = tmp_path / "external.sock"
    with pytest.raises(ConfigError, match="managed-local"):
        Client(socket=socket_path, auto_start_local_server=True)
