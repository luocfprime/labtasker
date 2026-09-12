from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, cast

ROOT = Path(__file__).resolve().parents[2]
CLIENT_PROJECT = ROOT / "packages/labtasker-client"
TEST_DEPENDENCIES = (
    "hypothesis==6.125.0",
    "pytest==8.3.0",
    "pytest-timeout==2.3.1",
)


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def parse_arguments() -> tuple[Literal["minimum", "latest"], str]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("minimum", "latest"), required=True)
    parser.add_argument("--python", required=True)
    arguments = parser.parse_args()
    return cast(Literal["minimum", "latest"], arguments.profile), str(arguments.python)


def main() -> None:
    profile, python_version = parse_arguments()
    prefix = f"labtasker-client-{profile}-py{python_version.replace('.', '')}-"
    with tempfile.TemporaryDirectory(prefix=prefix) as temporary:
        environment = Path(temporary) / "venv"
        python = environment / "bin/python"
        subprocess.run(
            ("uv", "venv", "--no-project", "--python", python_version, str(environment)),
            cwd=temporary,
            check=True,
        )
        if profile == "minimum":
            run(
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--resolution",
                "lowest-direct",
                str(CLIENT_PROJECT),
                *TEST_DEPENDENCIES,
            )
            run(
                str(python),
                str(ROOT / "tests/compatibility/verify_direct_minimum.py"),
                "labtasker-client",
            )
        else:
            run(
                "uv",
                "pip",
                "install",
                "--python",
                str(python),
                "--resolution",
                "highest",
                str(CLIENT_PROJECT),
                *TEST_DEPENDENCIES,
            )
        run(str(python), "-m", "pytest", "tests/client")


if __name__ == "__main__":
    main()
