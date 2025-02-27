import argparse
from pathlib import Path

import tomlkit
from packaging.version import InvalidVersion, Version

from labtasker import __version__


def parse_version(tag: str) -> str:
    """Parse version tag (e.g. git tag v0.1.0) and validate it using PEP 440."""
    try:
        return str(Version(tag))
    except InvalidVersion:
        raise ValueError(f"Invalid version tag: {tag}")


def get_pyproject_version() -> str:
    """Retrieve the version from pyproject.toml."""
    pyproject_toml = Path("pyproject.toml")

    if pyproject_toml.exists():
        with pyproject_toml.open("rb") as f:
            pyproject = tomlkit.load(f)
        return pyproject.get("project", {}).get("version", "")

    raise ValueError(f"{pyproject_toml} not found")


def check_version_match(tag: str = None) -> bool:
    """Check if the version in pyproject.toml, the provided tag, and __version__ match.

    Args:
        tag: Optional Git tag (e.g., "v0.1.0").

    Returns: True if all versions match, False otherwise.

    """
    pyproject_version = get_pyproject_version()
    tag_version = parse_version(tag) if tag else None

    if tag:
        return pyproject_version == tag_version == __version__
    return pyproject_version == __version__


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check if version numbers match.")
    parser.add_argument(
        "--tag",
        type=str,
        help="The Git tag to compare, e.g., 'v0.1.0'. If omitted, only pyproject.toml and __version__ are compared.",
    )
    args = parser.parse_args()

    match = check_version_match(tag=args.tag)
    print(f"check version match: {match}")

    exit(0 if match else 1)
