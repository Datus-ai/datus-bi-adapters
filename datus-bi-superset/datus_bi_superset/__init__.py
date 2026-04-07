# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
# See http://www.apache.org/licenses/LICENSE-2.0 for details.

from datus_bi_core import adaptor_registry
from datus_bi_core.models import AuthType
from datus_bi_superset.adaptor import SupersetAdaptor


def register():
    adaptor_registry.register(
        "superset",
        SupersetAdaptor,
        auth_type=AuthType.LOGIN,
        display_name="Apache Superset",
        capabilities={
            "list_dashboards",
            "dashboard_write",
            "chart_write",
            "dataset_write",
        },
    )


__all__ = ["SupersetAdaptor", "register"]
