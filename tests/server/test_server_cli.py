from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from typer.testing import CliRunner

from labtasker_server import __version__
from labtasker_server.cli import app
from labtasker_server.local import LocalPaths, RuntimeMetadata, read_metadata

runner = CliRunner()


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
