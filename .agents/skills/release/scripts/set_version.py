#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VERSION_PATTERN = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:(?:a|b|rc)(?:0|[1-9]\d*))?$"
)
PYPROJECTS = (
    ROOT / "pyproject.toml",
    ROOT / "packages/labtasker/pyproject.toml",
    ROOT / "packages/labtasker-client/pyproject.toml",
    ROOT / "packages/labtasker-server/pyproject.toml",
)
INIT_FILES = (
    ROOT / "packages/labtasker-client/src/labtasker/__init__.py",
    ROOT / "packages/labtasker-server/src/labtasker_server/__init__.py",
)
PLUGIN_FILES = (
    ROOT / ".claude-plugin/plugin.json",
    ROOT / ".claude-plugin/marketplace.json",
)
LOCK_NAMES = {
    "labtasker-workspace",
    "labtasker",
    "labtasker-client",
    "labtasker-server",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Synchronize the Labtasker workspace version.")
    parser.add_argument("version", help="PEP 440 release such as 2.1.0 or 2.1.0rc1")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify source metadata and uv.lock without changing files.",
    )
    return parser.parse_args()


def project_version(path: Path) -> str:
    return str(tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"])


def init_version(path: Path) -> str:
    match = re.search(r'^__version__ = "([^"]+)"$', path.read_text(encoding="utf-8"), re.M)
    if match is None:
        raise SystemExit(f"missing __version__ assignment: {path.relative_to(ROOT)}")
    return match.group(1)


def plugin_version(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(a|b|rc)(\d+)", version)
    if match is None:
        return version
    phase = {"a": "alpha", "b": "beta", "rc": "rc"}[match.group(2)]
    return f"{match.group(1)}-{phase}.{match.group(3)}"


def manifest_version(path: Path) -> str:
    document = json.loads(path.read_text(encoding="utf-8"))
    if path.name == "marketplace.json":
        return str(document["plugins"][0]["version"])
    return str(document["version"])


def replace_project_version(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^(\[project\]\nname = "[^"]+"\nversion = ")[^"]+("$)',
        rf"\g<1>{version}\g<2>",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"could not update project version: {path.relative_to(ROOT)}")
    path.write_text(updated, encoding="utf-8")


def metapackage_dependency_versions() -> set[str]:
    document = tomllib.loads(
        (ROOT / "packages/labtasker/pyproject.toml").read_text(encoding="utf-8")
    )
    return {
        str(dependency).split("==", 1)[1]
        for dependency in document["project"]["dependencies"]
        if str(dependency).startswith(("labtasker-client==", "labtasker-server=="))
    }


def replace_metapackage_dependency_versions(version: str) -> None:
    path = ROOT / "packages/labtasker/pyproject.toml"
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^(  "labtasker-(?:client|server)==)[^"]+(",)$',
        rf"\g<1>{version}\g<2>",
        text,
    )
    if count != 2:
        raise SystemExit("could not update metapackage dependency versions")
    path.write_text(updated, encoding="utf-8")


def replace_init_version(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^__version__ = "[^"]+"$',
        f'__version__ = "{version}"',
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"could not update __version__: {path.relative_to(ROOT)}")
    path.write_text(updated, encoding="utf-8")


def replace_manifest_version(path: Path, version: str) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    if path.name == "marketplace.json":
        document["plugins"][0]["version"] = version
    else:
        document["version"] = version
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def check_source(version: str) -> None:
    actual = {
        **{str(path.relative_to(ROOT)): project_version(path) for path in PYPROJECTS},
        **{str(path.relative_to(ROOT)): init_version(path) for path in INIT_FILES},
        **{str(path.relative_to(ROOT)): manifest_version(path) for path in PLUGIN_FILES},
    }
    expected = {
        **{str(path.relative_to(ROOT)): version for path in (*PYPROJECTS, *INIT_FILES)},
        **{str(path.relative_to(ROOT)): plugin_version(version) for path in PLUGIN_FILES},
    }
    mismatches = {path: value for path, value in actual.items() if value != expected[path]}
    if mismatches:
        details = ", ".join(
            f"{path}={value} (expected {expected[path]})"
            for path, value in sorted(mismatches.items())
        )
        raise SystemExit(f"version mismatch: {details}")
    if metapackage_dependency_versions() != {version}:
        raise SystemExit("metapackage dependency versions do not match the release")


def check_lock(version: str) -> None:
    lock_path = ROOT / "uv.lock"
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    actual = {
        str(package["name"]): str(package["version"])
        for package in lock["package"]
        if package["name"] in LOCK_NAMES
    }
    expected = {name: version for name in LOCK_NAMES}
    if actual != expected:
        raise SystemExit(f"uv.lock version mismatch; expected {expected}, found {actual}")


def main() -> None:
    args = parse_args()
    version = str(args.version)
    if VERSION_PATTERN.fullmatch(version) is None:
        raise SystemExit("VERSION must look like 2.1.0 or 2.1.0rc1")

    if args.check:
        check_source(version)
        check_lock(version)
        print(f"Labtasker version is consistently {version}.")
        return

    current = {project_version(path) for path in PYPROJECTS} | {
        init_version(path) for path in INIT_FILES
    }
    if len(current) != 1:
        raise SystemExit(f"refusing to update inconsistent source versions: {sorted(current)}")
    for path in PYPROJECTS:
        replace_project_version(path, version)
    replace_metapackage_dependency_versions(version)
    for path in INIT_FILES:
        replace_init_version(path, version)
    for path in PLUGIN_FILES:
        replace_manifest_version(path, plugin_version(version))
    print(f"Updated Labtasker from {current.pop()} to {version}; run 'uv lock' next.")


if __name__ == "__main__":
    main()
