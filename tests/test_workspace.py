from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

import labtasker
import labtasker_server

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_VERSION = str(
    tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
)


def test_workspace_and_all_distributions_share_one_version() -> None:
    assert labtasker.__version__ == WORKSPACE_VERSION
    assert labtasker_server.__version__ == WORKSPACE_VERSION
    assert importlib.metadata.version("labtasker") == WORKSPACE_VERSION
    assert importlib.metadata.version("labtasker-client") == WORKSPACE_VERSION
    assert importlib.metadata.version("labtasker-server") == WORKSPACE_VERSION


def test_distribution_metadata_keeps_packages_independent_and_aligned() -> None:
    client = tomllib.loads(
        (ROOT / "packages/labtasker-client/pyproject.toml").read_text(encoding="utf-8")
    )
    server = tomllib.loads(
        (ROOT / "packages/labtasker-server/pyproject.toml").read_text(encoding="utf-8")
    )
    metapackage = tomllib.loads(
        (ROOT / "packages/labtasker/pyproject.toml").read_text(encoding="utf-8")
    )
    client_dependencies = "\n".join(client["project"]["dependencies"]).lower()
    server_dependencies = "\n".join(server["project"]["dependencies"]).lower()

    for forbidden in ("fastapi", "sqlalchemy", "alembic", "uvicorn"):
        assert forbidden not in client_dependencies
    assert "labtasker" not in server_dependencies
    assert client["project"]["name"] == "labtasker-client"
    assert server["project"]["name"] == "labtasker-server"
    assert metapackage["project"]["name"] == "labtasker"
    assert set(metapackage["project"]["dependencies"]) == {
        f"labtasker-client=={WORKSPACE_VERSION}",
        f"labtasker-server=={WORKSPACE_VERSION}",
    }
    assert (
        metapackage["project"]["version"]
        == client["project"]["version"]
        == server["project"]["version"]
        == WORKSPACE_VERSION
    )
    assert (
        metapackage["project"]["license"]
        == client["project"]["license"]
        == server["project"]["license"]
        == "Apache-2.0"
    )
    assert (
        metapackage["project"]["license-files"]
        == client["project"]["license-files"]
        == server["project"]["license-files"]
        == ["LICENSE"]
    )
    assert client["project"]["scripts"] == {"labtasker": "labtasker.cli:app"}
    assert server["project"]["scripts"] == {"labtasker-server": "labtasker_server.cli:app"}
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert (ROOT / "packages/labtasker-client/LICENSE").read_text() == license_text
    assert (ROOT / "packages/labtasker-server/LICENSE").read_text() == license_text
    assert (ROOT / "packages/labtasker/LICENSE").read_text() == license_text


def test_agent_skill_has_one_cross_agent_distribution_source() -> None:
    skill = ROOT / "skills/labtasker/SKILL.md"
    repository_link = ROOT / ".agents/skills/labtasker"
    plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    marketplace_plugin = marketplace["plugins"][0]

    assert skill.is_file()
    assert skill.read_text(encoding="utf-8").startswith("---\nname: labtasker\n")
    assert repository_link.is_symlink()
    assert repository_link.resolve() == skill.parent.resolve()
    assert plugin["name"] == "labtasker-skill"
    assert plugin["skills"] == "./skills"
    assert marketplace["name"] == "labtasker"
    assert len(marketplace["plugins"]) == 1
    assert marketplace_plugin["name"] == "labtasker-skill"
    assert marketplace_plugin["source"] == "./"
    assert marketplace_plugin["version"] == plugin["version"]

    version_check = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".agents/skills/release/scripts/set_version.py"),
            "--check",
            WORKSPACE_VERSION,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert version_check.stdout == f"Labtasker version is consistently {WORKSPACE_VERSION}.\n"


def test_workspace_contains_exactly_three_members() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["uv"]["workspace"]["members"] == [
        "packages/labtasker",
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
