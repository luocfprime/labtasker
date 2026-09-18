from __future__ import annotations

import json
import os
import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from labtasker_server import __version__
from labtasker_server.cli import app, daemon_command
from labtasker_server.local import (
    DaemonConfig,
    _remove_verified_stale_socket,
    http_health,
)

runner = CliRunner()


def test_version_and_missing_connection_have_no_state_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    version = runner.invoke(app, ["--version"])
    missing = runner.invoke(app, ["serve"])

    assert version.exit_code == 0
    assert version.stdout == f"labtasker-server {__version__}\n"
    assert missing.exit_code == 2
    assert "Missing option '--connection'" in missing.stderr
    assert not (tmp_path / ".labtasker").exists()


def test_server_help_exposes_one_serve_and_root_management() -> None:
    root = runner.invoke(app, ["--help"])
    serve = runner.invoke(app, ["serve", "--help"])
    coordinator = runner.invoke(app, ["_ensure-daemon", "--help"])
    child = runner.invoke(app, ["_daemon", "--help"])

    assert root.exit_code == serve.exit_code == coordinator.exit_code == child.exit_code == 0
    assert "serve" in root.stdout
    assert "start" not in root.stdout
    for command in ("status", "stop", "logs"):
        assert command in root.stdout
    assert "_ensure-daemon" not in root.stdout
    assert "_daemon" not in root.stdout
    assert "--connection <http|socket>" in serve.stdout
    assert "[required]" in serve.stdout
    assert "--labtasker-root" in coordinator.stdout
    for option in ("--root-lock-fd", "--readiness-fd", "--generation"):
        assert option in child.stdout
    for removed in ("--token", "--workers", "--reload", "--log-level"):
        assert removed not in serve.stdout


def test_http_serve_uses_transport_specific_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}
    application = object()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("labtasker_server.cli.create_app", lambda settings: application)

    def run(app: object, **kwargs: object) -> None:
        observed["app"] = app
        observed.update(kwargs)

    monkeypatch.setattr("labtasker_server.cli.uvicorn.run", run)
    result = runner.invoke(app, ["serve", "--connection", "http"])

    assert result.exit_code == 0, result.output
    assert observed["app"] is application
    assert observed["host"] == "127.0.0.1"
    assert observed["port"] == 8000
    assert "fd" not in observed
    assert not (tmp_path / ".labtasker").exists()


@pytest.mark.parametrize(
    "arguments",
    [
        ["serve", "--connection", "http", "--socket", "/tmp/server.sock"],
        ["serve", "--connection", "socket", "--host", "127.0.0.1"],
        ["serve", "--connection", "socket", "--port", "8000"],
    ],
)
def test_serve_rejects_transport_option_mixtures(arguments: list[str]) -> None:
    result = runner.invoke(app, arguments)
    assert result.exit_code == 2
    assert "valid only with --connection" in result.stderr


def test_socket_serve_uses_explicit_database_and_cleans_socket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}
    socket_path = Path("/tmp") / f"labtasker-cli-test-{os.getpid()}.sock"
    database_path = tmp_path / "data/server.db"

    def create(settings: object) -> object:
        observed["settings"] = settings
        return object()

    def run(application: object, **kwargs: object) -> None:
        observed["application"] = application
        observed.update(kwargs)

    monkeypatch.setattr("labtasker_server.cli.create_app", create)
    monkeypatch.setattr("labtasker_server.cli.uvicorn.run", run)
    result = runner.invoke(
        app,
        [
            "serve",
            "--connection",
            "socket",
            "--socket",
            str(socket_path),
            "--database",
            str(database_path),
            "--database-filesystem",
            "shared",
        ],
    )

    assert result.exit_code == 0, result.output
    settings = observed["settings"]
    assert settings.database == database_path.resolve()  # type: ignore[attr-defined]
    assert settings.database_filesystem == "shared"  # type: ignore[attr-defined]
    assert settings.token is None  # type: ignore[attr-defined]
    assert "fd" in observed
    assert not socket_path.exists()


def test_status_is_read_only_and_has_stable_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "state"
    monkeypatch.setattr("labtasker_server.local.runtime_directory", lambda: tmp_path / "runtime")
    monkeypatch.setattr(
        "labtasker_server.ownership.runtime_directory", lambda: tmp_path / "runtime"
    )
    result = runner.invoke(app, ["status", "--labtasker-root", str(root)])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "state": "stopped",
        "labtasker_root": str(root.resolve()),
        "database": None,
        "database_filesystem": None,
        "connection": None,
        "host": None,
        "port": None,
        "socket": None,
        "log": str(root.resolve() / "server.log"),
        "pid": None,
        "version": None,
    }
    assert not root.exists()
    assert not (tmp_path / "runtime").exists()


def test_daemon_publishes_identity_only_after_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    root = tmp_path / "root"
    config = DaemonConfig(
        labtasker_root=root,
        database=root / "server.db",
        database_filesystem="local",
        connection="http",
        host="127.0.0.1",
        port=8000,
        socket=None,
        authentication_enabled=False,
        server_version=__version__,
    )

    class Listener:
        def fileno(self) -> int:
            return 1

        def close(self) -> None:
            events.append("listener-close")

    lock = SimpleNamespace(close=lambda: events.append("lock-close"))
    monkeypatch.setattr(
        "labtasker_server.cli._resolve_serve_config", lambda **_: (config, object())
    )
    monkeypatch.setattr("labtasker_server.cli._inherited_root_lock", lambda *_: lock)
    monkeypatch.setattr(
        "labtasker_server.cli.create_app", lambda _: events.append("app") or object()
    )
    monkeypatch.setattr(
        "labtasker_server.cli._bind_listener",
        lambda _: events.append("bind") or Listener(),
    )
    monkeypatch.setattr(
        "labtasker_server.cli.make_metadata",
        lambda *_args, **kwargs: SimpleNamespace(listener_bound=kwargs["listener_bound"]),
    )
    monkeypatch.setattr(
        "labtasker_server.cli.write_metadata",
        lambda _paths, metadata: events.append(f"metadata-{metadata.listener_bound}"),
    )
    monkeypatch.setattr(
        "labtasker_server.cli.uvicorn.run", lambda *_args, **_kwargs: events.append("run")
    )
    monkeypatch.setattr("labtasker_server.cli._dispose_application", lambda _: None)
    monkeypatch.setattr("labtasker_server.cli.remove_stopped_artifacts", lambda *_a, **_k: None)
    read_fd, write_fd = os.pipe()
    try:
        daemon_command(
            labtasker_root=root,
            database=config.database,
            database_filesystem="local",
            connection="http",
            root_lock_fd=123,
            readiness_fd=write_fd,
            generation="generation",
            started_at=1.0,
            host="127.0.0.1",
            port=8000,
            socket_path=None,
        )
        assert os.read(read_fd, 64) == b"generation"
    finally:
        os.close(read_fd)

    assert events.index("metadata-False") < events.index("app") < events.index("bind")
    assert events.index("bind") < events.index("metadata-True") < events.index("run")


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="requires Unix sockets")
def test_stale_cleanup_refuses_any_live_socket_listener() -> None:
    with tempfile.TemporaryDirectory(prefix="lt-", dir="/tmp") as directory:
        path = Path(directory) / "external.sock"
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
            listener.listen()
            with pytest.raises(RuntimeError, match="live listener"):
                _remove_verified_stale_socket(path)
            assert path.exists()
        path.unlink()


def test_http_health_uses_normal_address_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    response = iter(
        (
            b'HTTP/1.1 200 OK\r\n\r\n{"status":"ok","api_version":"2","database":"ok"}',
            b"",
        )
    )
    observed: dict[str, object] = {}

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def sendall(self, request: bytes) -> None:
            observed["request"] = request

        def recv(self, _: int) -> bytes:
            return next(response)

    def connect(address: tuple[str, int], *, timeout: float) -> Connection:
        observed["address"] = address
        observed["timeout"] = timeout
        return Connection()

    monkeypatch.setattr("labtasker_server.local.socket.create_connection", connect)

    assert http_health("localhost", 8123)
    assert observed["address"] == ("localhost", 8123)
