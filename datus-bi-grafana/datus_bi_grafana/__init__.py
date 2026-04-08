# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

from datus_bi_core import adapter_registry
from datus_bi_core.models import AuthType
from datus_bi_grafana.adapter import GrafanaAdapter


def register():
    adapter_registry.register(
        "grafana",
        GrafanaAdapter,
        auth_type=AuthType.API_KEY,
        display_name="Grafana",
        capabilities={"list_dashboards", "dashboard_write", "chart_write"},
    )


__all__ = ["GrafanaAdapter", "register"]
