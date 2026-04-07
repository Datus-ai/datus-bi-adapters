#!/usr/bin/env python3
"""
E2E script: create "2025年活动趋势分析" dashboard in Grafana
using datus_daily_activity_2025 table from PostgreSQL (Superset's postgres).

Requirements:
  - Grafana running at localhost:3000
  - Service account token with Admin permission
  - PostgreSQL (Superset's) at localhost:5433, db=superset_examples
  - Table public.datus_daily_activity_2025 already populated
"""

import sys
import os

# Allow running from the package root
sys.path.insert(0, os.path.dirname(__file__))

from datus_bi_grafana.adaptor import GrafanaAdaptor
from datus_bi_core.models import AuthParam, ChartSpec, DashboardSpec

GRAFANA_URL = os.getenv("GRAFANA_URL", "http://localhost:3000")
GRAFANA_TOKEN = os.environ["GRAFANA_TOKEN"]  # required: service account token with Admin permission

# PostgreSQL connection info (host.docker.internal so Grafana container can reach host-mapped port 5433)
PG_URL = os.getenv("PG_URL", "host.docker.internal:5433")
PG_USER = os.getenv("PG_USER", "superset")
PG_PASSWORD = os.getenv("PG_PASSWORD", "superset")
PG_DATABASE = os.getenv("PG_DATABASE", "superset_examples")
DS_NAME = "Superset-PostgreSQL"

SQL = "SELECT day, activity_count FROM public.datus_daily_activity_2025 ORDER BY day"
DASHBOARD_TITLE = "2025年活动趋势分析"
CHART_TITLE = "每日活动数量"


def main():
    adaptor = GrafanaAdaptor(
        api_base_url=GRAFANA_URL,
        auth_params=AuthParam(api_key=GRAFANA_TOKEN),
        dialect="postgresql",
    )

    # Step 1: create or find PostgreSQL datasource
    print(f"[1/3] Finding or creating datasource '{DS_NAME}' ...")
    ds = adaptor.find_or_create_datasource(
        name=DS_NAME,
        db_type="grafana-postgresql-datasource",
        url=PG_URL,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DATABASE,
        extra_json_data={
            "sslmode": "disable",
            "postgresVersion": 1500,
            "timescaledb": False,
        },
    )
    ds_uid = ds.get("uid") or str(ds.get("id", ""))
    ds_type = ds.get("type", "grafana-postgresql-datasource")
    print(f"    datasource uid={ds_uid}  type={ds_type}")

    # Step 2: create empty dashboard
    print(f"[2/3] Creating dashboard '{DASHBOARD_TITLE}' ...")
    dash_spec = DashboardSpec(
        title=DASHBOARD_TITLE,
        description="通过 Datus 自动创建 - 展示 2025 年每日活动数量趋势",
    )
    dashboard = adaptor.create_dashboard(dash_spec)
    dash_uid = str(dashboard.id)
    print(f"    dashboard uid={dash_uid}")

    # Step 3: create bar chart panel with SQL query
    print(f"[3/3] Creating chart '{CHART_TITLE}' ...")
    chart_spec = ChartSpec(
        chart_type="bar",
        title=CHART_TITLE,
        description="每天的活动数量统计",
        sql=SQL,
        extra={
            "datasource_uid": ds_uid,
            "datasource_type": ds_type,
            # Use time series x-axis style for bar chart
            "fieldConfig": {
                "defaults": {
                    "custom": {
                        "fillOpacity": 80,
                        "gradientMode": "none",
                        "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                        "lineWidth": 1,
                    }
                },
                "overrides": [],
            },
            "options": {
                "barRadius": 0,
                "barWidth": 0.97,
                "fullHighlight": False,
                "groupWidth": 0.7,
                "legend": {"calcs": [], "displayMode": "list", "placement": "bottom", "showLegend": True},
                "orientation": "auto",
                "stacking": "none",
                "tooltip": {"mode": "single", "sort": "none"},
                "xTickLabelRotation": -45,
                "xTickLabelSpacing": 0,
            },
            "gridPos": {"h": 12, "w": 24, "x": 0, "y": 0},
        },
    )
    chart = adaptor.create_chart(chart_spec, dashboard_id=dash_uid)
    print(f"    chart id={chart.id}")

    print(f"\nDone! Open Grafana dashboard at: {GRAFANA_URL}/d/{dash_uid}")
    adaptor.close()


if __name__ == "__main__":
    main()
