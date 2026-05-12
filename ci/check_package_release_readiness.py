#!/usr/bin/env python3

"""Validate package-level adapter release readiness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from packaging.utils import canonicalize_name

from package_release import (
    REPO_ROOT,
    build_package_wheels,
    check_tag_available,
    dependency_build_order,
    dependent_packages,
    load_workspace_packages,
    lower_bound,
    parse_canonical_version,
    require_package,
    smoke_import_package,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=REPO_ROOT, help="Repository root to validate"
    )
    parser.add_argument(
        "--package", required=True, help="Workspace package name to validate"
    )
    parser.add_argument("--expected-version", help="Expected package version")
    parser.add_argument(
        "--check-tag-available",
        action="store_true",
        help="Fail if <package>-v<version> exists",
    )
    parser.add_argument(
        "--check-dependent-bounds",
        action="store_true",
        help="Require workspace dependents to declare a lower bound equal to the target package version",
    )
    parser.add_argument(
        "--build",
        action="store_true",
        help="Build the package and workspace package dependencies",
    )
    parser.add_argument(
        "--skip-import-smoke",
        action="store_true",
        help="Skip installing/importing the built wheel",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    errors: list[str] = []

    try:
        packages = load_workspace_packages(repo_root)
        target = require_package(packages, args.package)
        if args.expected_version is not None:
            expected_version = parse_canonical_version(args.expected_version)
            if target.version != expected_version:
                errors.append(
                    f"{target.name} version mismatch: pyproject.toml has {target.version}, expected {expected_version}"
                )
        if args.check_tag_available:
            errors.extend(check_tag_available(repo_root, target.name, target.version))

        if args.check_dependent_bounds:
            for dependent in dependent_packages(packages, target):
                requirement = dependent.dependencies[canonicalize_name(target.name)]
                bound = lower_bound(requirement)
                if bound != target.version:
                    errors.append(
                        f"{dependent.name} must depend on {target.name}>={target.version}; "
                        f"found {requirement}"
                    )

        if errors:
            raise ValueError("\n".join(errors))

        build_order = dependency_build_order(packages, target)
        if args.build:
            wheels = build_package_wheels(repo_root, build_order)
            if not args.skip_import_smoke:
                smoke_import_package(repo_root, target, wheels)
    except Exception as exc:
        print("Package release readiness checks failed:", file=sys.stderr)
        for line in str(exc).splitlines():
            print(f"  - {line}", file=sys.stderr)
        return 1

    print(f"Package release readiness checks passed for {target.name} {target.version}")
    print("Build order:")
    for package in dependency_build_order(packages, target):
        print(f"  - {package.name}")
    if args.check_dependent_bounds:
        dependents = dependent_packages(packages, target)
        print("Dependent lower bounds:")
        if dependents:
            for dependent in dependents:
                requirement = dependent.dependencies[canonicalize_name(target.name)]
                print(f"  - {dependent.name}: {requirement}")
        else:
            print("  - <none>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
