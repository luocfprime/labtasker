from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_DEPENDENCIES = (
    "httpx==0.28.1",
    "hypothesis==6.125.0",
    "pytest==8.3.0",
    "pytest-timeout==2.3.1",
)


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def parse_python_version() -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    return str(parser.parse_args().python)


def main() -> None:
    python_version = parse_python_version()
    prefix = f"labtasker-server-minimum-py{python_version.replace('.', '')}-"
    with tempfile.TemporaryDirectory(prefix=prefix) as temporary:
        environment = Path(temporary) / "venv"
        python = environment / "bin/python"
        subprocess.run(
            ("uv", "venv", "--no-project", "--python", python_version, str(environment)),
            cwd=temporary,
            check=True,
        )
        run(
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            "--resolution",
            "lowest-direct",
            str(ROOT / "packages/labtasker-server"),
            *TEST_DEPENDENCIES,
        )
        run(
            str(python),
            str(ROOT / "tests/compatibility/verify_direct_minimum.py"),
            "labtasker-server",
        )
        run(str(python), "-m", "pytest", "tests/server")


if __name__ == "__main__":
    main()
