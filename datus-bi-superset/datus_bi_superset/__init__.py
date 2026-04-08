# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

from datus_bi_core import adapter_registry
from datus_bi_core.models import AuthType
from datus_bi_superset.adapter import SupersetAdapter


def register():
    adapter_registry.register(
        "superset",
        SupersetAdapter,
        auth_type=AuthType.LOGIN,
        display_name="Apache Superset",
        capabilities={
            "list_dashboards",
            "dashboard_write",
            "chart_write",
            "dataset_write",
        },
    )


__all__ = ["SupersetAdapter", "register"]
