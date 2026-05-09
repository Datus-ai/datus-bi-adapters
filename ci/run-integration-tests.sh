#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ALL_ADAPTERS=(superset grafana)
DOCKER_COMPOSE=()

usage() {
  cat <<'USAGE'
Usage: ci/run-integration-tests.sh [--list] [--dry-run] [--changed base-ref] [adapter ...]
       ci/run-integration-tests.sh --cleanup-only

Runs Docker-backed BI adapter integration tests.

Options:
  --changed REF    Select impacted adapters from git diff REF...HEAD.
  --list           List configured adapter targets.
  --dry-run        Print selected adapters without starting Docker.
  --cleanup-only   Stop all configured integration compose projects.
  -h, --help       Show this help.
USAGE
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 127
  fi
}

detect_docker_compose() {
  if docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker compose)
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE=(docker-compose)
    return 0
  fi
  return 1
}

install_docker_compose() {
  local version="${DOCKER_COMPOSE_VERSION:-v2.32.4}"
  local os
  local machine
  local arch
  local bin_dir
  local bin_path
  local url

  if ! command -v curl >/dev/null 2>&1; then
    echo "Missing required command: curl; cannot install Docker Compose." >&2
    return 1
  fi

  os="$(uname -s | tr '[:upper:]' '[:lower:]')"
  case "$os" in
    linux|darwin) ;;
    *)
      echo "Unsupported OS for automatic Docker Compose install: $os" >&2
      return 1
      ;;
  esac

  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64) arch="x86_64" ;;
    aarch64|arm64) arch="aarch64" ;;
    *)
      echo "Unsupported architecture for automatic Docker Compose install: $machine" >&2
      return 1
      ;;
  esac

  bin_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/datus-docker-compose"
  bin_path="$bin_dir/docker-compose-$version-$os-$arch"
  url="https://github.com/docker/compose/releases/download/$version/docker-compose-$os-$arch"

  mkdir -p "$bin_dir"
  if [ ! -x "$bin_path" ]; then
    echo "Installing Docker Compose $version to $bin_path"
    curl -fsSL --retry 3 -o "$bin_path" "$url"
    chmod +x "$bin_path"
  fi

  DOCKER_COMPOSE=("$bin_path")
}

ensure_docker_compose() {
  detect_docker_compose || install_docker_compose
}

docker_compose() {
  if [ "${#DOCKER_COMPOSE[@]}" -eq 0 ]; then
    if ! ensure_docker_compose; then
      echo "Docker Compose is not available through 'docker compose' or 'docker-compose'." >&2
      return 127
    fi
  fi
  "${DOCKER_COMPOSE[@]}" "$@"
}

preflight() {
  require_command uv
  require_command docker
  if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon is not reachable. Start Docker and retry." >&2
    exit 1
  fi
  if ! ensure_docker_compose; then
    echo "Docker Compose is not available through 'docker compose' or 'docker-compose'." >&2
    exit 1
  fi
}

is_known_adapter() {
  local requested="$1"
  local adapter
  for adapter in "${ALL_ADAPTERS[@]}"; do
    if [ "$adapter" = "$requested" ]; then
      return 0
    fi
  done
  return 1
}

adapter_compose() {
  case "$1" in
    superset) echo "datus-bi-superset/tests/integration/docker-compose.yml" ;;
    grafana) echo "datus-bi-grafana/tests/integration/docker-compose.yml" ;;
    *) echo "Unknown adapter '$1'" >&2; return 1 ;;
  esac
}

adapter_test_path() {
  case "$1" in
    superset) echo "datus-bi-superset/tests/integration" ;;
    grafana) echo "datus-bi-grafana/tests/integration" ;;
    *) echo "Unknown adapter '$1'" >&2; return 1 ;;
  esac
}

adapter_package() {
  case "$1" in
    superset) echo "datus-bi-superset" ;;
    grafana) echo "datus-bi-grafana" ;;
    *) echo "Unknown adapter '$1'" >&2; return 1 ;;
  esac
}

adapter_services() {
  case "$1" in
    superset) echo "postgres:300 superset:1200" ;;
    grafana) echo "postgres:300 grafana:300" ;;
    *) echo "Unknown adapter '$1'" >&2; return 1 ;;
  esac
}

list_adapters() {
  local adapter
  for adapter in "${ALL_ADAPTERS[@]}"; do
    printf '%s\t%s\t%s\t%s\n' \
      "$adapter" \
      "$(adapter_package "$adapter")" \
      "$(adapter_compose "$adapter")" \
      "$(adapter_test_path "$adapter")"
  done
}

export_adapter_env() {
  case "$1" in
    superset)
      export SUPERSET_PORT="${SUPERSET_PORT:-18088}"
      export SUPERSET_POSTGRES_PORT="${SUPERSET_POSTGRES_PORT:-15433}"
      export SUPERSET_URL="${SUPERSET_URL:-http://127.0.0.1:${SUPERSET_PORT}}"
      export SUPERSET_USER="${SUPERSET_USER:-admin}"
      export SUPERSET_PASS="${SUPERSET_PASS:-admin}"
      ;;
    grafana)
      export GRAFANA_PORT="${GRAFANA_PORT:-13000}"
      export GRAFANA_POSTGRES_PORT="${GRAFANA_POSTGRES_PORT:-15434}"
      export GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:${GRAFANA_PORT}}"
      export GRAFANA_USER="${GRAFANA_USER:-admin}"
      export GRAFANA_PASS="${GRAFANA_PASS:-admin123}"
      ;;
  esac
}

adapter_env_summary() {
  case "$1" in
    superset) echo "env: SUPERSET_URL=$SUPERSET_URL SUPERSET_PORT=$SUPERSET_PORT SUPERSET_POSTGRES_PORT=$SUPERSET_POSTGRES_PORT" ;;
    grafana) echo "env: GRAFANA_URL=$GRAFANA_URL GRAFANA_PORT=$GRAFANA_PORT GRAFANA_POSTGRES_PORT=$GRAFANA_POSTGRES_PORT" ;;
  esac
}

compose_down() {
  local adapter="$1"
  local compose_file
  compose_file="$(adapter_compose "$adapter")"
  if [ -f "$compose_file" ]; then
    docker_compose -f "$compose_file" down -v --remove-orphans >/dev/null 2>&1 || true
  fi
}

cleanup_all() {
  local adapter
  for adapter in "${ALL_ADAPTERS[@]}"; do
    compose_down "$adapter"
  done
}

cleanup_only=0
dry_run=0
changed_mode=0
changed_base=""
requested_adapters=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --cleanup-only)
      cleanup_only=1
      shift
      ;;
    --list)
      list_adapters
      exit 0
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --changed)
      changed_mode=1
      if [ -z "${2:-}" ]; then
        echo "--changed requires a base ref" >&2
        exit 2
      fi
      changed_base="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while [ "$#" -gt 0 ]; do
        requested_adapters+=("$1")
        shift
      done
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      requested_adapters+=("$1")
      shift
      ;;
  esac
done

if [ "$cleanup_only" -eq 1 ]; then
  cleanup_all
  exit 0
fi

wait_for_service_health() {
  local compose_file="$1"
  local service_name="$2"
  local timeout_seconds="$3"
  local container_id=""
  local status=""
  local deadline=$((SECONDS + timeout_seconds))

  container_id="$(docker_compose -f "$compose_file" ps -q "$service_name")"
  if [ -z "$container_id" ]; then
    echo "No container found for service '$service_name' in $compose_file" >&2
    docker_compose -f "$compose_file" ps || true
    return 1
  fi

  while [ "$SECONDS" -lt "$deadline" ]; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null || echo unknown)"
    if [ "$status" = "healthy" ] || [ "$status" = "running" ]; then
      echo "Service '$service_name' is $status"
      return 0
    fi
    sleep 5
  done

  echo "Timed out waiting for service '$service_name' from $compose_file" >&2
  docker_compose -f "$compose_file" ps || true
  docker_compose -f "$compose_file" logs --tail=200 || true
  return 1
}

adapters_from_changed_files() {
  local base_ref="$1"
  local changed_files=""
  changed_files="$(
    {
      git diff --name-only "${base_ref}...HEAD"
      git diff --name-only --cached
      git diff --name-only
      git ls-files --others --exclude-standard
    } | awk 'NF && !seen[$0]++'
  )"

  if [ -z "$changed_files" ]; then
    return 0
  fi

  if echo "$changed_files" | grep -Eq '^(pyproject\.toml|uv\.lock|ci/|\.github/workflows/|datus-bi-core/)'; then
    printf '%s\n' "${ALL_ADAPTERS[@]}"
    return 0
  fi

  if echo "$changed_files" | grep -Eq '^datus-bi-superset/'; then
    echo "superset"
  fi
  if echo "$changed_files" | grep -Eq '^datus-bi-grafana/'; then
    echo "grafana"
  fi
}

selected_adapters=()
if [ "$changed_mode" -eq 1 ]; then
  while IFS= read -r adapter; do
    [ -n "$adapter" ] && selected_adapters+=("$adapter")
  done < <(adapters_from_changed_files "$changed_base" | awk '!seen[$0]++')
else
  if [ "${#requested_adapters[@]}" -gt 0 ]; then
    selected_adapters=("${requested_adapters[@]}")
  fi
fi

if [ "${#selected_adapters[@]}" -eq 0 ] && [ "$changed_mode" -eq 1 ]; then
  echo "No BI adapter changes detected; skipping integration tests."
  exit 0
fi

if [ "${#selected_adapters[@]}" -eq 0 ]; then
  selected_adapters=("${ALL_ADAPTERS[@]}")
fi

for adapter in "${selected_adapters[@]}"; do
  if ! is_known_adapter "$adapter"; then
    echo "Unknown adapter '$adapter'. Use --list to see valid adapter names." >&2
    exit 2
  fi
done

if [ "$dry_run" -eq 1 ]; then
  for adapter in "${selected_adapters[@]}"; do
    export_adapter_env "$adapter"
    echo ""
    echo "=== Integration tests: $adapter ==="
    echo "package: $(adapter_package "$adapter")"
    echo "compose: $(adapter_compose "$adapter")"
    echo "tests: $(adapter_test_path "$adapter")"
    echo "services: $(adapter_services "$adapter")"
    adapter_env_summary "$adapter"
  done
  exit 0
fi

preflight
trap cleanup_all EXIT

for adapter in "${selected_adapters[@]}"; do
  compose_file="$(adapter_compose "$adapter")"
  test_path="$(adapter_test_path "$adapter")"
  package="$(adapter_package "$adapter")"

  echo ""
  echo "=== Integration tests: $adapter ==="
  compose_down "$adapter"
  export_adapter_env "$adapter"
  docker_compose -f "$compose_file" up -d --build

  for spec in $(adapter_services "$adapter"); do
    service_name="${spec%%:*}"
    timeout_seconds="${spec##*:}"
    wait_for_service_health "$compose_file" "$service_name" "$timeout_seconds"
  done

  uv run --with pytest --with pytest-asyncio --package "$package" pytest "$test_path" -m integration --tb=short --verbose

  compose_down "$adapter"
done
