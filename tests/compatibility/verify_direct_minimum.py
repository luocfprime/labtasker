from __future__ import annotations

import argparse
from importlib.metadata import requires, version

from packaging.requirements import Requirement
from packaging.version import Version


def declared_floor(requirement: Requirement) -> Version:
    inclusive_floors = [
        Version(specifier.version)
        for specifier in requirement.specifier
        if specifier.operator in {">=", "~=", "=="} and "*" not in specifier.version
    ]
    if not inclusive_floors:
        raise RuntimeError(f"{requirement} has no exact inclusive lower bound")
    floor = max(inclusive_floors)
    if not requirement.specifier.contains(floor, prereleases=True):
        raise RuntimeError(f"{requirement} does not include its derived lower bound {floor}")
    return floor


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("distribution")
    distribution = parser.parse_args().distribution

    direct_requirements = requires(distribution)
    if direct_requirements is None:
        raise RuntimeError(f"{distribution} has no dependency metadata")
    for raw_requirement in direct_requirements:
        requirement = Requirement(raw_requirement)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        expected = declared_floor(requirement)
        actual = Version(version(requirement.name))
        if actual != expected:
            raise RuntimeError(
                f"{requirement.name} resolved to {actual}; declared direct minimum is {expected}"
            )
        print(f"{requirement.name}=={actual}")


if __name__ == "__main__":
    main()
