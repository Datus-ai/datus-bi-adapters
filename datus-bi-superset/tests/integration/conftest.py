# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.

import os

import httpx
import pytest

from datus_bi_core.models import AuthParam
from datus_bi_superset.adaptor import SupersetAdaptor

SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://localhost:8088")
SUPERSET_USER = os.environ.get("SUPERSET_USER", "admin")
SUPERSET_PASS = os.environ.get("SUPERSET_PASS", "admin")


def _is_superset_running() -> bool:
    try:
        resp = httpx.get(f"{SUPERSET_URL}/health", timeout=5.0)
        return resp.is_success
    except Exception:
        return False


# Docker-internal URI (used when Superset connects from inside the container)
_EXAMPLES_URI = (
    "postgresql+psycopg2://superset:superset@postgres:5432/superset_examples"
)
_EXAMPLES_DB_NAME = "datus_test_examples"


def _ensure_examples_database(adaptor: "SupersetAdaptor") -> int:
    """Return id of the examples database connection.

    After ``superset load-examples`` runs, an 'examples' connection is already
    registered.  If not found, create one pointing at the Docker postgres service.
    """
    dbs = adaptor.list_bi_databases()
    if dbs:
        # Prefer a database matching the expected name; fall back to first
        for db in dbs:
            if db.get("name") == _EXAMPLES_DB_NAME:
                return db["id"]
        return dbs[0]["id"]

    # Fallback: create connection pointing to the Docker-internal postgres service
    data = adaptor._request_json(
        "POST",
        "database",
        json={
            "database_name": _EXAMPLES_DB_NAME,
            "sqlalchemy_uri": _EXAMPLES_URI,
            "expose_in_sqllab": True,
        },
    )
    result = data.get("result", data)
    db_id = data.get("id") or result.get("id")
    if not db_id:
        raise RuntimeError(f"Failed to create examples database in Superset: {data}")
    return db_id


@pytest.fixture(scope="session")
def superset_adaptor():
    if not _is_superset_running():
        pytest.skip(
            f"Superset not reachable at {SUPERSET_URL}. Run: docker compose up -d"
        )
    return SupersetAdaptor(
        api_base_url=SUPERSET_URL,
        auth_params=AuthParam(username=SUPERSET_USER, password=SUPERSET_PASS),
        dialect="postgresql",
    )


@pytest.fixture(scope="session")
def superset_db_id(superset_adaptor):
    """Return id of the examples database connection (created by superset load-examples)."""
    return _ensure_examples_database(superset_adaptor)
