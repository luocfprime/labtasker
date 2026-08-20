from __future__ import annotations

import importlib.metadata
import tomllib
from pathlib import Path

import labtasker
import labtasker_server

ROOT = Path(__file__).resolve().parents[1]


def test_both_distributions_start_at_version_2() -> None:
    assert labtasker.__version__ == "2.0.0"
    assert labtasker_server.__version__ == "2.0.0"
    assert importlib.metadata.version("labtasker") == "2.0.0"
    assert importlib.metadata.version("labtasker-server") == "2.0.0"


def test_client_package_does_not_depend_on_server_stack() -> None:
    pyproject = tomllib.loads(
        (ROOT / "packages/labtasker-client/pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = "\n".join(pyproject["project"]["dependencies"]).lower()

    for forbidden in ("fastapi", "sqlalchemy", "alembic", "uvicorn"):
        assert forbidden not in dependencies


def test_workspace_contains_exactly_two_members() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["tool"]["uv"]["workspace"]["members"] == [
        "packages/labtasker-client",
        "packages/labtasker-server",
    ]
