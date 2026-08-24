from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from labtasker_server.cli import app

runner = CliRunner()


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
