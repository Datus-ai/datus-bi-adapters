# Datus BI Adapters

A uv workspace containing modular BI platform adapters for Datus.

## Packages

| Package | Description |
|---------|-------------|
| `datus-bi-core` | Core BI abstractions: base class, mixins, models, registry |
| `datus-bi-superset` | Apache Superset adapter |
| `datus-bi-grafana` | Grafana adapter |

## Development

```bash
uv sync                          # Install all workspace packages
uv run pytest                    # Run all tests
uv run ruff format .             # Format
uv run ruff check --fix .        # Lint
```

## Installation (end users)

```bash
pip install datus-bi-superset    # Installs datus-bi-core automatically
pip install datus-bi-grafana
```
