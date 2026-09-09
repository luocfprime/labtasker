from __future__ import annotations

import json
import os
import socket
import time
from dataclasses import asdict
from pathlib import Path

import pytest
from typer.testing import CliRunner

from labtasker_server import __version__, local
from labtasker_server.cli import app
from labtasker_server.local import LocalPaths, RuntimeMetadata, read_metadata

runner = CliRunner()


@pytest.mark.parametrize("generation", [None, "old"])
def test_stopped_artifact_cleanup_holds_database_ownership(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, generation: str | None
) -> None:
    paths = local.local_paths(tmp_path)
    fd = local.try_acquire_database(paths)
    assert fd is not None
    metadata = local.make_metadata(
        paths,
        generation="old",
        role="daemon",
        pid=os.getpid(),
        automatic_attempt_at=time.time(),
        database_fd=fd,
        server_version=__version__,
    )
    local.write_metadata(paths, metadata)
    os.close(fd)
    with socket.socket(socket.AF_UNIX) as bound:
        bound.bind(str(paths.socket))
        original = local.remove_stale_artifacts

        def concurrent_start_is_blocked(actual: LocalPaths) -> None:
            competing_fd = local.try_acquire_database(actual)
            if competing_fd is not None:
                os.close(competing_fd)
            assert competing_fd is None
            original(actual)

        monkeypatch.setattr(local, "remove_stale_artifacts", concurrent_start_is_blocked)
        local.remove_stopped_artifacts(paths, generation=generation)
    assert not paths.socket.exists()
    assert not paths.metadata.exists()


def test_stopped_cleanup_preserves_new_owner_and_missing_database(tmp_path: Path) -> None:
    paths = local.local_paths(tmp_path)
    fd = local.try_acquire_database(paths)
    assert fd is not None
    metadata = local.make_metadata(
        paths,
        generation="new",
        role="daemon",
        pid=os.getpid(),
        automatic_attempt_at=time.time(),
        database_fd=fd,
        server_version=__version__,
    )
    local.write_metadata(paths, metadata)
    try:
        local.remove_stopped_artifacts(paths, generation="old")
        assert local.read_metadata(paths) == metadata
    finally:
        os.close(fd)
    local.remove_stopped_artifacts(paths, generation="old")
    assert local.read_metadata(paths) == metadata
    paths.database.unlink()
    local.remove_stopped_artifacts(paths)
    assert not paths.database.exists()
    assert local.read_metadata(paths) == metadata
    paths.metadata.unlink()


def test_daemon_socket_cleanup_holds_ownership_and_preserves_throttle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = local.local_paths(tmp_path)
    fd = local.try_acquire_database(paths)
    assert fd is not None
    metadata = local.make_metadata(
        paths,
        generation="old",
        role="daemon",
        pid=os.getpid(),
        automatic_attempt_at=time.time(),
        database_fd=fd,
        server_version=__version__,
    )
    local.write_metadata(paths, metadata)
    with socket.socket(socket.AF_UNIX) as bound:
        bound.bind(str(paths.socket))
        # Initialization may fail while ownership is still held. Cleanup must
        # leave the socket untouched until the next coordinator owns the file.
        local.remove_stopped_artifacts(paths, generation="old", preserve_metadata=True)
        assert paths.socket.exists()
        os.close(fd)
        original = local.read_metadata

        def competing_start_after_generation_read(actual: LocalPaths) -> RuntimeMetadata | None:
            result = original(actual)
            competing_fd = local.try_acquire_database(actual)
            if competing_fd is not None:
                os.close(competing_fd)
            assert competing_fd is None
            return result

        monkeypatch.setattr(local, "read_metadata", competing_start_after_generation_read)
        local.remove_stopped_artifacts(paths, generation="old", preserve_metadata=True)
        assert not paths.socket.exists()
        assert original(paths) == metadata
    paths.metadata.unlink()


def test_version_reports_server_distribution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["--version"])
    help_result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert result.stdout == f"labtasker-server {__version__}\n"
    assert result.stderr == ""
    assert "--version" in help_result.stdout
    assert __version__ not in help_result.stdout
    assert not (tmp_path / ".labtasker").exists()


def test_malformed_runtime_metadata_is_ignored(tmp_path: Path) -> None:
    paths = LocalPaths(
        directory=tmp_path,
        database=tmp_path / ".labtasker/server.db",
        log=tmp_path / ".labtasker/server.log",
        runtime_directory=tmp_path / "runtime",
        socket=tmp_path / "runtime/server.sock",
        metadata=tmp_path / "runtime/server.json",
    )
    paths.runtime_directory.mkdir()
    valid = asdict(
        RuntimeMetadata(
            metadata_version=1,
            generation="generation",
            role="daemon",
            pid=123,
            process_start_marker="proc:1",
            directory=str(paths.directory),
            database=str(paths.database),
            database_device=1,
            database_inode=2,
            automatic_attempt_at=123.0,
            server_version="2.0.0",
        )
    )
    paths.metadata.write_text(json.dumps(valid), encoding="utf-8")
    assert read_metadata(paths) == RuntimeMetadata(**valid)

    malformed_values = {
        "metadata_version": True,
        "generation": 1,
        "role": 1,
        "pid": "123",
        "process_start_marker": None,
        "directory": 1,
        "database": 1,
        "database_device": "1",
        "database_inode": "2",
        "automatic_attempt_at": float("nan"),
        "server_version": 2,
    }
    for field, value in malformed_values.items():
        payload = {**valid, field: value}
        paths.metadata.write_text(json.dumps(payload), encoding="utf-8")
        assert read_metadata(paths) is None, field


def test_server_cli_has_explicit_serve_and_local_management_commands() -> None:
    root = runner.invoke(app, ["--help"])
    serve = runner.invoke(app, ["serve", "--help"])
    assert root.exit_code == serve.exit_code == 0
    assert "Commands:" in root.stdout
    assert "serve" in root.stdout
    for command in ("start", "status", "stop", "logs"):
        assert command in root.stdout
    assert "Usage: root serve [OPTIONS]" in serve.stdout
    assert "Initialize the database and run one Labtasker v2 Server process." in serve.stdout
    assert "LABTASKER_SERVER_TOKEN" in serve.stdout
    assert "Run only one Server process for each SQLite file." in serve.stdout
    assert "non-loopback address requires a token" in serve.stdout
    assert "labtasker-server serve" in serve.stdout
    assert "╭" not in root.stdout + serve.stdout
    for removed in ("--token", "--workers", "--reload", "--log-level"):
        assert removed not in serve.stdout


def test_serve_uses_documented_defaults_and_environment_token(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def run(app: object, **kwargs: object) -> None:
        observed.update(kwargs)
        observed["app"] = app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LABTASKER_SERVER_TOKEN", "secret")
    monkeypatch.setattr("labtasker_server.cli.uvicorn.run", run)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0
    assert observed == {
        "app": observed["app"],
        "host": "127.0.0.1",
        "port": 8000,
        "log_level": "info",
        "log_config": observed["log_config"],
    }
    log_config = observed["log_config"]
    assert isinstance(log_config, dict)
    formatter = log_config["formatters"]["labtasker-server"]
    assert formatter["format"] == (
        "%(asctime)s.%(msecs)03dZ %(levelname)s [labtasker-server] %(message)s"
    )
    assert formatter["datefmt"] == "%Y-%m-%dT%H:%M:%S"
    assert (tmp_path / ".labtasker/server.db").exists()
    assert (tmp_path / ".labtasker/.gitignore").read_text() == "*\n!.gitignore\n"


def test_serve_rejects_nonloopback_without_token(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["serve", "--host", "0.0.0.0", "--database", str(tmp_path / "db")],
    )
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "[labtasker-server] Server configuration error: "
        "A token is required when binding to a non-loopback host.\n"
    )
    assert "Traceback" not in result.stderr
