# Copyright 2025-present DatusAI, Inc.
# Licensed under the Apache License, Version 2.0.
#
# Integration tests — require a running Grafana instance.
# Start with: docker compose up -d (from datus-bi-adapters root)
# Run with:   uv run --package datus-bi-grafana pytest datus-bi-grafana/tests/integration/ -v -m integration

import pytest

from datus_bi_core import DatusBiException
from datus_bi_core.models import ChartSpec, DashboardSpec

pytestmark = pytest.mark.integration

_DASHBOARD_TITLE = "[Datus-Test] Integration Dashboard"


class TestGrafanaDashboards:
    def test_list_dashboards_returns_list(self, grafana_adaptor):
        results = grafana_adaptor.list_dashboards()
        assert isinstance(results, list)

    def test_list_dashboards_with_search(self, grafana_adaptor):
        results = grafana_adaptor.list_dashboards(search="nonexistent_xyz_abc")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_create_update_delete_dashboard(self, grafana_adaptor):
        spec = DashboardSpec(
            title=_DASHBOARD_TITLE, description="Created by integration test"
        )
        created = grafana_adaptor.create_dashboard(spec)
        assert created.id is not None
        assert created.name == _DASHBOARD_TITLE

        # Search for it
        found = grafana_adaptor.list_dashboards(search="Datus-Test")
        assert any(str(d.id) == str(created.id) for d in found)

        # Update
        update_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} Updated")
        updated = grafana_adaptor.update_dashboard(created.id, update_spec)
        assert updated.name == f"{_DASHBOARD_TITLE} Updated"

        # Delete
        deleted = grafana_adaptor.delete_dashboard(created.id)
        assert deleted is True

        # Verify gone
        after = grafana_adaptor.list_dashboards(search="Datus-Test")
        assert all(str(d.id) != str(created.id) for d in after)

    def test_get_dashboard_info(self, grafana_adaptor):
        spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} GetTest")
        created = grafana_adaptor.create_dashboard(spec)
        try:
            info = grafana_adaptor.get_dashboard_info(created.id)
            assert info is not None
            assert info.name == f"{_DASHBOARD_TITLE} GetTest"
        finally:
            grafana_adaptor.delete_dashboard(created.id)

    def test_parse_dashboard_id_from_url(self, grafana_adaptor):
        uid = grafana_adaptor.parse_dashboard_id(
            "http://localhost:3000/d/abc123/my-dashboard"
        )
        assert uid == "abc123"


class TestGrafanaCharts:
    def test_create_chart_without_dashboard_id_raises(self, grafana_adaptor):
        spec = ChartSpec(chart_type="bar", title="Test Chart")
        with pytest.raises(DatusBiException, match="dashboard_id"):
            grafana_adaptor.create_chart(spec)

    def test_create_chart_appended_to_dashboard(self, grafana_adaptor):
        # Create a dashboard first
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} ChartTest")
        dashboard = grafana_adaptor.create_dashboard(dash_spec)
        try:
            # Create chart (panel) inside the dashboard
            chart_spec = ChartSpec(
                chart_type="timeseries",
                title="[Datus-Test] Timeseries Panel",
                description="Integration test panel",
            )
            chart = grafana_adaptor.create_chart(chart_spec, dashboard_id=dashboard.id)
            assert chart.id is not None
            assert chart.name == "[Datus-Test] Timeseries Panel"

            # Verify panel is in dashboard
            charts = grafana_adaptor.list_charts(dashboard.id)
            assert any(str(c.id) == str(chart.id) for c in charts)

        finally:
            grafana_adaptor.delete_dashboard(dashboard.id)

    def test_create_multiple_chart_types(self, grafana_adaptor):
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} MultiCharts")
        dashboard = grafana_adaptor.create_dashboard(dash_spec)
        created_ids = []
        try:
            for chart_type in ["bar", "line", "pie", "table", "big_number"]:
                spec = ChartSpec(
                    chart_type=chart_type, title=f"[Datus-Test] {chart_type}"
                )
                chart = grafana_adaptor.create_chart(spec, dashboard_id=dashboard.id)
                assert chart.id is not None
                created_ids.append(chart.id)

            charts = grafana_adaptor.list_charts(dashboard.id)
            assert len(charts) == len(created_ids)
        finally:
            grafana_adaptor.delete_dashboard(dashboard.id)


class TestGrafanaGetChart:
    def test_get_chart_by_id(self, grafana_adaptor):
        """Create a dashboard with a chart, then retrieve the chart by id."""
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} GetChart")
        dashboard = grafana_adaptor.create_dashboard(dash_spec)
        try:
            chart_spec = ChartSpec(
                chart_type="bar",
                title="[Datus-Test] Bar Panel",
                description="A test bar panel",
            )
            created = grafana_adaptor.create_chart(chart_spec, dashboard_id=dashboard.id)

            chart = grafana_adaptor.get_chart(created.id, dashboard_id=dashboard.id)
            assert chart is not None
            assert str(chart.id) == str(created.id)
            assert chart.name == "[Datus-Test] Bar Panel"
        finally:
            grafana_adaptor.delete_dashboard(dashboard.id)

    def test_get_chart_not_found(self, grafana_adaptor):
        """get_chart returns None for a non-existent panel id."""
        dash_spec = DashboardSpec(title=f"{_DASHBOARD_TITLE} GetChartMissing")
        dashboard = grafana_adaptor.create_dashboard(dash_spec)
        try:
            chart = grafana_adaptor.get_chart(99999, dashboard_id=dashboard.id)
            assert chart is None
        finally:
            grafana_adaptor.delete_dashboard(dashboard.id)

    def test_get_chart_without_dashboard_id_raises(self, grafana_adaptor):
        """get_chart raises DatusBiException when dashboard_id is missing."""
        with pytest.raises(DatusBiException, match="dashboard_id"):
            grafana_adaptor.get_chart(1)

    def test_update_chart_raises(self, grafana_adaptor):
        """Grafana update_chart always raises because it needs dashboard context."""
        spec = ChartSpec(chart_type="bar", title="Test")
        with pytest.raises(DatusBiException, match="dashboard_id"):
            grafana_adaptor.update_chart(1, spec)

    def test_delete_chart_returns_false(self, grafana_adaptor):
        """Grafana delete_chart returns False because it needs dashboard context."""
        result = grafana_adaptor.delete_chart(1)
        assert result is False


class TestGrafanaDatasets:
    def test_list_datasets(self, grafana_adaptor):
        # list_datasets returns Grafana datasources
        datasets = grafana_adaptor.list_datasets(dashboard_id="")
        assert isinstance(datasets, list)
        # Grafana should have at least one built-in datasource
        for ds in datasets:
            assert ds.id is not None
            assert ds.name is not None

    def test_get_dataset(self, grafana_adaptor):
        """Get a datasource by id — pick the first from list_datasets."""
        datasets = grafana_adaptor.list_datasets(dashboard_id="")
        if not datasets:
            pytest.skip("No datasources configured in Grafana")
        first = datasets[0]
        ds = grafana_adaptor.get_dataset(first.id)
        assert ds is not None
        assert ds.id == first.id
        assert ds.name == first.name

    def test_get_dataset_not_found(self, grafana_adaptor):
        """get_dataset returns None for a non-existent datasource id."""
        ds = grafana_adaptor.get_dataset(999999)
        assert ds is None
