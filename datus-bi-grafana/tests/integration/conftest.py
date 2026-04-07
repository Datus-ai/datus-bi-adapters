# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.

import os

import httpx
import pytest

from datus_bi_core.models import AuthParam
from datus_bi_grafana.adaptor import GrafanaAdaptor

GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3000")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "admin")
GRAFANA_PASS = os.environ.get("GRAFANA_PASS", "admin123")


def _is_grafana_running() -> bool:
    try:
        resp = httpx.get(f"{GRAFANA_URL}/api/health", timeout=5.0)
        return resp.is_success
    except Exception:
        return False


def _get_or_create_api_token(url: str, user: str, password: str) -> str:
    """Create a Grafana Service Account token for testing."""
    auth = (user, password)
    headers = {"Content-Type": "application/json"}

    # Create service account (ignore error if already exists)
    sa_resp = httpx.post(
        f"{url}/api/serviceaccounts",
        auth=auth,
        headers=headers,
        json={"name": "datus-integration-test-sa", "role": "Admin"},
        timeout=10.0,
    )
    sa_data = sa_resp.json()
    sa_id = sa_data.get("id")
    if not sa_id:
        # May already exist — search for it
        list_resp = httpx.get(
            f"{url}/api/serviceaccounts/search", auth=auth, timeout=10.0
        )
        for sa in list_resp.json().get("serviceAccounts", []):
            if sa.get("name") == "datus-integration-test-sa":
                sa_id = sa["id"]
                break
    if not sa_id:
        raise RuntimeError(f"Could not create/find Grafana service account: {sa_data}")

    # Delete existing token with same name if present
    existing_tokens = httpx.get(
        f"{url}/api/serviceaccounts/{sa_id}/tokens", auth=auth, timeout=10.0
    ).json()
    for t in existing_tokens if isinstance(existing_tokens, list) else []:
        if t.get("name") == "datus-test-token":
            httpx.delete(
                f"{url}/api/serviceaccounts/{sa_id}/tokens/{t['id']}",
                auth=auth,
                timeout=10.0,
            )

    # Create token
    token_resp = httpx.post(
        f"{url}/api/serviceaccounts/{sa_id}/tokens",
        auth=auth,
        headers=headers,
        json={"name": "datus-test-token"},
        timeout=10.0,
    )
    token = token_resp.json().get("key")
    if not token:
        raise RuntimeError(f"Could not create Grafana token: {token_resp.text}")
    return token


@pytest.fixture(scope="session")
def grafana_api_token():
    if not _is_grafana_running():
        pytest.skip(
            f"Grafana not reachable at {GRAFANA_URL}. Run: docker compose up -d"
        )
    return _get_or_create_api_token(GRAFANA_URL, GRAFANA_USER, GRAFANA_PASS)


@pytest.fixture(scope="session")
def grafana_adaptor(grafana_api_token):
    return GrafanaAdaptor(
        api_base_url=GRAFANA_URL,
        auth_params=AuthParam(api_key=grafana_api_token),
        dialect="postgres",
    )
