from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import labtasker
import labtasker_server

ROOT = Path(__file__).resolve().parents[1]


def test_both_distributions_start_at_version_2() -> None:
    assert labtasker.__version__ == "2.0.0"
    assert labtasker_server.__version__ == "2.0.0"
    assert importlib.metadata.version("labtasker") == "2.0.0"
    assert importlib.metadata.version("labtasker-server") == "2.0.0"


def test_distribution_metadata_keeps_packages_independent_and_aligned() -> None:
    client = tomllib.loads(
        (ROOT / "packages/labtasker-client/pyproject.toml").read_text(encoding="utf-8")
    )
    server = tomllib.loads(
        (ROOT / "packages/labtasker-server/pyproject.toml").read_text(encoding="utf-8")
    )
    client_dependencies = "\n".join(client["project"]["dependencies"]).lower()
    server_dependencies = "\n".join(server["project"]["dependencies"]).lower()

    for forbidden in ("fastapi", "sqlalchemy", "alembic", "uvicorn"):
        assert forbidden not in client_dependencies
    assert "labtasker" not in server_dependencies
    assert client["project"]["name"] == "labtasker"
    assert server["project"]["name"] == "labtasker-server"
    assert client["project"]["version"] == server["project"]["version"] == "2.0.0"
    assert client["project"]["license"] == server["project"]["license"] == "Apache-2.0"
    assert client["project"]["license-files"] == server["project"]["license-files"] == ["LICENSE"]
    assert client["project"]["scripts"] == {"labtasker": "labtasker.cli:app"}
    assert server["project"]["scripts"] == {"labtasker-server": "labtasker_server.cli:app"}
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert (ROOT / "packages/labtasker-client/LICENSE").read_text() == license_text
    assert (ROOT / "packages/labtasker-server/LICENSE").read_text() == license_text


def test_workspace_contains_exactly_two_members() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["uv"]["workspace"]["members"] == [
        "packages/labtasker-client",
        "packages/labtasker-server",
    ]


def test_import_has_no_configuration_stream_logging_or_hook_side_effects() -> None:
    script = """
import logging, os, random, sys
stdout, stderr = sys.stdout, sys.stderr
root_handlers = list(logging.getLogger().handlers)
named_handlers = list(logging.getLogger("labtasker").handlers)
hooks = []
if hasattr(os, "register_at_fork"):
    os.register_at_fork = lambda **kwargs: hooks.append(kwargs)
import labtasker
assert sys.stdout is stdout and sys.stderr is stderr
assert logging.getLogger().handlers == root_handlers
assert logging.getLogger("labtasker").handlers == named_handlers
assert hooks == []
assert "_default_client" not in vars(labtasker)
"""
    subprocess.run([sys.executable, "-c", script], check=True)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork behavior is POSIX-specific")
def test_worker_tee_fork_child_does_not_inherit_active_run_log(tmp_path: Path) -> None:
    from labtasker.tee import WorkerTee

    log_path = tmp_path / "run.log"
    read_fd, write_fd = os.pipe()
    with WorkerTee() as tee, tee.capture(log_path):
        child = os.fork()
        if child == 0:  # pragma: no branch - the child exits immediately
            os.close(read_fd)
            print("child-output", flush=True)
            os.write(write_fd, b"done")
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        assert os.read(read_fd, 4) == b"done"
        os.close(read_fd)
        _, status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(status) == 0
        print("parent-output", flush=True)
    assert "parent-output" in log_path.read_text()
    assert "child-output" not in log_path.read_text()
