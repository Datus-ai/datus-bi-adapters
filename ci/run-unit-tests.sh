#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PACKAGE_SPECS=(
  "datus-bi-core:datus-bi-core/tests/unit"
  "datus-bi-superset:datus-bi-superset/tests/unit"
  "datus-bi-grafana:datus-bi-grafana/tests/unit"
)

usage() {
  cat <<'USAGE'
Usage: ci/run-unit-tests.sh [--list] [--dry-run] [package ...]

Runs deterministic unit tests for BI adapter workspace packages.

Options:
  --list      List configured package targets.
  --dry-run   Print selected package targets without running pytest.
  -h, --help  Show this help.
USAGE
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 127
  fi
}

list_packages() {
  local spec package test_path
  for spec in "${PACKAGE_SPECS[@]}"; do
    package="${spec%%:*}"
    test_path="${spec#*:}"
    printf '%s\t%s\n' "$package" "$test_path"
  done
}

requested_packages=()
dry_run=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --list)
      list_packages
      exit 0
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [ "$#" -gt 0 ]; do
        requested_packages+=("$1")
        shift
      done
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      requested_packages+=("$1")
      shift
      ;;
  esac
done

should_run_package() {
  local package="$1"
  if [ "${#requested_packages[@]}" -eq 0 ]; then
    return 0
  fi

  local requested
  for requested in "${requested_packages[@]}"; do
    if [ "$requested" = "$package" ]; then
      return 0
    fi
  done
  return 1
}

require_command uv

for spec in "${PACKAGE_SPECS[@]}"; do
  package="${spec%%:*}"
  test_path="${spec#*:}"

  if ! should_run_package "$package"; then
    continue
  fi

  echo ""
  echo "=== Unit tests: $package ==="
  if [ "$dry_run" -eq 1 ]; then
    echo "pytest target: $test_path"
    continue
  fi

  uv run --with pytest --with pytest-asyncio --package "$package" pytest \
    "$test_path" \
    -m "not integration" \
    --tb=short \
    --verbose
done
