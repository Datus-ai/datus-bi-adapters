# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
#
# Integration tests — require a running Superset instance.
# Start with: docker compose up -d (from datus-bi-adapters root)
# Run with:   uv run --package datus-bi-superset pytest datus-bi-superset/tests/integration/ -v -m integration

import pytest

from datus_bi_core.models import DashboardSpec

pytestmark = pytest.mark.integration

_DASHBOARD_TITLE = "[Datus-Test] Integration Dashboard"


class TestSupersetDashboards:
    def test_list_dashboards_returns_list(self, superset_adaptor):
        results = superset_adaptor.list_dashboards()
        assert isinstance(results, list)

    def test_list_dashboards_with_search(self, superset_adaptor):
        results = superset_adaptor.list_dashboards(search="nonexistent_xyz_abc")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_create_update_delete_dashboard(self, superset_adaptor):
        # Create
        spec = DashboardSpec(
            title=_DASHBOARD_TITLE, description="Created by integration test"
        )
        created = superset_adaptor.create_dashboard(spec)
        assert created.id is not None
        assert created.name == _DASHBOARD_TITLE

        # Search for it
        found = superset_adaptor.list_dashboards(search="Datus-Test")
        assert any(str(d.id) == str(created.id) for d in found)

        # Update
        update_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} Updated")
        updated = superset_adaptor.update_dashboard(created.id, update_spec)
        assert updated.name == f"{_DASHBOARD_TITLE} Updated"

        # Delete
        deleted = superset_adaptor.delete_dashboard(created.id)
        assert deleted is True

        # Verify gone
        after = superset_adaptor.list_dashboards(search="Datus-Test")
        assert all(str(d.id) != str(created.id) for d in after)

    def test_get_dashboard_info(self, superset_adaptor):
        # Create a dashboard, get it, then clean up
        spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} GetTest")
        created = superset_adaptor.create_dashboard(spec)
        try:
            info = superset_adaptor.get_dashboard_info(created.id)
            assert info is not None
            assert info.id is not None
        finally:
            superset_adaptor.delete_dashboard(created.id)


class TestSupersetDatabases:
    def test_list_bi_databases(self, superset_adaptor):
        dbs = superset_adaptor.list_bi_databases()
        assert isinstance(dbs, list)
        # Each entry should have id and name
        for db in dbs:
            assert "id" in db
            assert "name" in db


class TestSupersetCharts:
    def test_create_update_delete_chart_with_dashboard(
        self, superset_adaptor, superset_db_id
    ):
        from datus_bi_core.models import ChartSpec

        db_id = superset_db_id

        # Create dataset first
        from datus_bi_core.models import DatasetSpec

        dataset_spec = DatasetSpec(
            name="datus_test_integration_dataset",
            sql="SELECT 1 AS metric, 'A' AS dimension",
            database_id=db_id,
        )
        dataset = superset_adaptor.create_dataset(dataset_spec)
        assert dataset.id is not None

        # Create dashboard
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} Charts")
        dashboard = superset_adaptor.create_dashboard(dash_spec)

        try:
            # Create chart
            chart_spec = ChartSpec(
                chart_type="big_number",
                title="[Datus-Test] Total",
                dataset_id=dataset.id,
                metrics=["count"],
            )
            chart = superset_adaptor.create_chart(chart_spec)
            assert chart.id is not None
            assert chart.name == "[Datus-Test] Total"

            # Add chart to dashboard
            added = superset_adaptor.add_chart_to_dashboard(dashboard.id, chart.id)
            assert added is True

            # Update chart
            update_spec = ChartSpec(
                chart_type="table",
                title="[Datus-Test] Table",
                dataset_id=dataset.id,
            )
            updated = superset_adaptor.update_chart(chart.id, update_spec)
            assert updated.id is not None

            # Delete chart
            superset_adaptor.delete_chart(chart.id)
        finally:
            superset_adaptor.delete_dashboard(dashboard.id)
            superset_adaptor.delete_dataset(dataset.id)
