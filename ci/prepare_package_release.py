#!/usr/bin/env python3

"""Prepare package-level release metadata changes for adapter workspaces."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from package_release import (
    REPO_ROOT,
    check_tag_available,
    dependent_packages,
    load_workspace_packages,
    parse_canonical_version,
    require_package,
    update_dependency_lower_bound,
    update_project_version,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=REPO_ROOT, help="Repository root to update"
    )
    parser.add_argument(
        "--package", required=True, help="Workspace package name to release"
    )
    parser.add_argument(
        "--version", required=True, help="New canonical PEP 440 package version"
    )
    parser.add_argument(
        "--update-dependent-bounds",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Update lower bounds in workspace packages that depend on the released package",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print planned changes without writing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        version = parse_canonical_version(args.version)
        packages = load_workspace_packages(repo_root)
        target = require_package(packages, args.package)
        if version <= target.version:
            raise ValueError(
                f"Release version must advance current {target.name} version {target.version}; got {version}"
            )

        tag_errors = check_tag_available(repo_root, target.name, version)
        if tag_errors:
            raise ValueError(tag_errors[0])

        dependents = dependent_packages(packages, target)
        changed: list[Path] = []
        if update_project_version(target.pyproject_path, version, dry_run=args.dry_run):
            changed.append(target.pyproject_path)

        if args.update_dependent_bounds:
            for dependent in dependents:
                if update_dependency_lower_bound(
                    dependent.pyproject_path,
                    target.name,
                    version,
                    dry_run=args.dry_run,
                ):
                    changed.append(dependent.pyproject_path)
    except Exception as exc:
        print(f"Release preparation failed: {exc}", file=sys.stderr)
        return 1

    if not changed:
        print(
            f"Release preparation produced no changes for {args.package} {args.version}",
            file=sys.stderr,
        )
        return 1

    action = "Would prepare" if args.dry_run else "Prepared"
    print(f"{action} package release metadata for {args.package} {args.version}")
    print("Changed files:")
    for path in sorted(set(changed)):
        print(f"  - {path.relative_to(repo_root)}")

    if args.update_dependent_bounds and dependents:
        print("Dependent packages checked:")
        for package in dependents:
            print(f"  - {package.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
