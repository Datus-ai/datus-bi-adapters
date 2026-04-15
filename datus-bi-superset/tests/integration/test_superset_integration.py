# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
#
# Integration tests — require a running Superset instance.
# Start with: docker compose up -d (from datus-bi-adapters root)
# Run with:   uv run --package datus-bi-superset pytest datus-bi-superset/tests/integration/ -v -m integration

import pytest

from datus_bi_core.models import ChartSpec, DashboardSpec, DatasetSpec

pytestmark = pytest.mark.integration

_DASHBOARD_TITLE = "[Datus-Test] Integration Dashboard"


class TestSupersetDashboards:
    def test_list_dashboards_returns_list(self, superset_adapter):
        results = superset_adapter.list_dashboards()
        assert isinstance(results, list)

    def test_list_dashboards_with_search(self, superset_adapter):
        results = superset_adapter.list_dashboards(search="nonexistent_xyz_abc")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_create_update_delete_dashboard(self, superset_adapter):
        # Create
        spec = DashboardSpec(
            title=_DASHBOARD_TITLE, description="Created by integration test"
        )
        created = superset_adapter.create_dashboard(spec)
        assert created.id is not None
        assert created.name == _DASHBOARD_TITLE

        # Search for it
        found = superset_adapter.list_dashboards(search="Datus-Test")
        assert any(str(d.id) == str(created.id) for d in found)

        # Update
        update_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} Updated")
        updated = superset_adapter.update_dashboard(created.id, update_spec)
        assert updated.name == f"{_DASHBOARD_TITLE} Updated"

        # Delete
        deleted = superset_adapter.delete_dashboard(created.id)
        assert deleted is True

        # Verify gone
        after = superset_adapter.list_dashboards(search="Datus-Test")
        assert all(str(d.id) != str(created.id) for d in after)

    def test_get_dashboard_info(self, superset_adapter):
        # Create a dashboard, get it, then clean up
        spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} GetTest")
        created = superset_adapter.create_dashboard(spec)
        try:
            info = superset_adapter.get_dashboard_info(created.id)
            assert info is not None
            assert info.id == created.id
            assert info.name == f"{_DASHBOARD_TITLE} GetTest"
        finally:
            superset_adapter.delete_dashboard(created.id)


class TestSupersetDatabases:
    def test_list_bi_databases(self, superset_adapter):
        dbs = superset_adapter.list_bi_databases()
        assert isinstance(dbs, list)
        assert len(dbs) > 0, "Superset should have at least one database configured"
        for db in dbs:
            assert "id" in db
            assert "name" in db


class TestSupersetCharts:
    def test_create_update_delete_chart_with_dashboard(
        self, superset_adapter, superset_db_id
    ):
        db_id = superset_db_id

        dataset_spec = DatasetSpec(
            name="datus_test_integration_dataset",
            sql="SELECT 1 AS metric, 'A' AS dimension",
            database_id=db_id,
        )
        dataset = superset_adapter.create_dataset(dataset_spec)
        assert dataset.id is not None

        # Create dashboard
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} Charts")
        dashboard = superset_adapter.create_dashboard(dash_spec)

        try:
            # Create chart
            chart_spec = ChartSpec(
                chart_type="big_number",
                title="[Datus-Test] Total",
                dataset_id=dataset.id,
                metrics=["count"],
            )
            chart = superset_adapter.create_chart(chart_spec)
            assert chart.id is not None
            assert chart.name == "[Datus-Test] Total"

            # Add chart to dashboard
            added = superset_adapter.add_chart_to_dashboard(dashboard.id, chart.id)
            assert added is True

            # Update chart
            update_spec = ChartSpec(
                chart_type="table",
                title="[Datus-Test] Table",
                dataset_id=dataset.id,
            )
            updated = superset_adapter.update_chart(chart.id, update_spec)
            assert updated.id is not None

            # Delete chart
            superset_adapter.delete_chart(chart.id)
        finally:
            superset_adapter.delete_dashboard(dashboard.id)
            superset_adapter.delete_dataset(dataset.id)

    def test_list_charts(self, superset_adapter, superset_db_id):
        """Create a dashboard with a chart, then list_charts and verify."""
        dataset_spec = DatasetSpec(
            name="datus_test_list_charts_ds",
            sql="SELECT 1 AS val",
            database_id=superset_db_id,
        )
        dataset = superset_adapter.create_dataset(dataset_spec)
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} ListCharts")
        dashboard = superset_adapter.create_dashboard(dash_spec)
        try:
            chart_spec = ChartSpec(
                chart_type="table",
                title="[Datus-Test] ListCharts Table",
                dataset_id=dataset.id,
            )
            chart = superset_adapter.create_chart(chart_spec)
            superset_adapter.add_chart_to_dashboard(dashboard.id, chart.id)

            charts = superset_adapter.list_charts(dashboard.id)
            assert isinstance(charts, list)
            assert len(charts) >= 1
            matching = [c for c in charts if str(c.id) == str(chart.id)]
            assert len(matching) == 1
            assert matching[0].name == "[Datus-Test] ListCharts Table"

            superset_adapter.delete_chart(chart.id)
        finally:
            superset_adapter.delete_dashboard(dashboard.id)
            superset_adapter.delete_dataset(dataset.id)

    def test_get_chart(self, superset_adapter, superset_db_id):
        """Create a chart with a dataset, then get_chart and verify structure."""
        dataset_spec = DatasetSpec(
            name="datus_test_get_chart_ds",
            sql="SELECT 1 AS revenue, 'A' AS region",
            database_id=superset_db_id,
        )
        dataset = superset_adapter.create_dataset(dataset_spec)
        try:
            chart_spec = ChartSpec(
                chart_type="table",
                title="[Datus-Test] GetChart Table",
                dataset_id=dataset.id,
                metrics=["revenue"],
            )
            created = superset_adapter.create_chart(chart_spec)

            chart = superset_adapter.get_chart(created.id)
            assert chart is not None
            assert chart.id is not None
            assert chart.name == "[Datus-Test] GetChart Table"
            assert chart.chart_type is not None

            superset_adapter.delete_chart(created.id)
        finally:
            superset_adapter.delete_dataset(dataset.id)


class TestSupersetDatasets:
    def test_list_datasets_from_dashboard(self, superset_adapter, superset_db_id):
        """Create dashboard + chart + dataset, then list_datasets."""
        dataset_spec = DatasetSpec(
            name="datus_test_list_ds",
            sql="SELECT 1 AS x",
            database_id=superset_db_id,
        )
        dataset = superset_adapter.create_dataset(dataset_spec)
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} ListDS")
        dashboard = superset_adapter.create_dashboard(dash_spec)
        try:
            chart_spec = ChartSpec(
                chart_type="table",
                title="[Datus-Test] DS Chart",
                dataset_id=dataset.id,
            )
            chart = superset_adapter.create_chart(chart_spec)
            superset_adapter.add_chart_to_dashboard(dashboard.id, chart.id)

            datasets = superset_adapter.list_datasets(dashboard.id)
            assert isinstance(datasets, list)
            assert len(datasets) >= 1
            assert any(str(ds.id) == str(dataset.id) for ds in datasets)

            superset_adapter.delete_chart(chart.id)
        finally:
            superset_adapter.delete_dashboard(dashboard.id)
            superset_adapter.delete_dataset(dataset.id)

    def test_get_dataset(self, superset_adapter, superset_db_id):
        """Create a dataset, then get_dataset and verify fields."""
        dataset_spec = DatasetSpec(
            name="datus_test_get_ds",
            sql="SELECT 1 AS col_a, 2 AS col_b",
            database_id=superset_db_id,
        )
        created = superset_adapter.create_dataset(dataset_spec)
        try:
            ds = superset_adapter.get_dataset(created.id)
            assert ds is not None
            assert ds.id == created.id
            assert ds.name == "datus_test_get_ds"
            assert ds.dialect is not None
        finally:
            superset_adapter.delete_dataset(created.id)

    def test_get_dataset_not_found(self, superset_adapter):
        """get_dataset returns None for a non-existent dataset id."""
        ds = superset_adapter.get_dataset(999999)
        assert ds is None

    def test_update_dataset(self, superset_adapter, superset_db_id):
        """Create a dataset, update its SQL, verify."""
        dataset_spec = DatasetSpec(
            name="datus_test_update_ds",
            sql="SELECT 1 AS old_col",
            database_id=superset_db_id,
        )
        created = superset_adapter.create_dataset(dataset_spec)
        try:
            update_spec = DatasetSpec(
                name="datus_test_update_ds",
                sql="SELECT 2 AS new_col",
                database_id=superset_db_id,
            )
            updated = superset_adapter.update_dataset(created.id, update_spec)
            assert updated.id == created.id
            assert updated.name == "datus_test_update_ds"
        finally:
            superset_adapter.delete_dataset(created.id)

    def test_parse_dashboard_id_from_url(self, superset_adapter):
        """parse_dashboard_id extracts id from various URL formats."""
        result = superset_adapter.parse_dashboard_id(
            "http://localhost:8088/superset/dashboard/42/"
        )
        assert result == "42"

        result = superset_adapter.parse_dashboard_id("99")
        assert result == 99

        result = superset_adapter.parse_dashboard_id("some-slug")
        assert result == "some-slug"
