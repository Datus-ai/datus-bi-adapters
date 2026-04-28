import pytest
from unittest.mock import patch

from datus_bi_core import DatusBiException
from datus_bi_core.models import AuthParam, ChartSpec, DashboardSpec
from datus_bi_grafana.adapter import GrafanaAdapter


def make_adapter():
    auth = AuthParam(api_key="test-api-key")
    return GrafanaAdapter(
        api_base_url="http://localhost:3000", auth_params=auth, dialect="postgres"
    )


class TestGrafanaReadOperations:
    def test_get_dashboard_info(self):
        adapter = make_adapter()
        mock_data = {
            "dashboard": {
                "title": "My Dashboard",
                "panels": [{"id": 1, "title": "Panel 1"}],
                "description": "",
            },
            "meta": {},
        }
        with patch.object(adapter, "_request_json", return_value=mock_data):
            result = adapter.get_dashboard_info("abc123")
        assert result.name == "My Dashboard"
        assert 1 in result.chart_ids

    def test_list_charts(self):
        adapter = make_adapter()
        mock_data = {
            "dashboard": {
                "panels": [{"id": 1, "title": "Panel 1", "type": "timeseries"}]
            },
        }
        with patch.object(adapter, "_request_json", return_value=mock_data):
            page = adapter.list_charts("abc123")
        # Grafana exposes the full panel list in one call, so total matches
        # len(items) and pagination is an in-memory slice.
        assert page.total == 1
        assert len(page.items) == 1
        assert page.items[0].chart_type == "timeseries"

    def test_list_dashboards(self):
        adapter = make_adapter()
        mock_data = [{"uid": "abc", "title": "My Dashboard"}]
        with patch.object(adapter, "_request_json", return_value=mock_data):
            page = adapter.list_dashboards(search="My")
        # Grafana /api/search doesn't report a total — total stays None and
        # the tool layer falls back to ``len(items) < limit`` heuristics.
        assert page.total is None
        assert len(page.items) == 1
        assert page.items[0].id == "abc"


class TestGrafanaWriteOperations:
    def test_create_dashboard(self):
        adapter = make_adapter()
        mock_data = {"uid": "new123", "url": "/d/new123/test", "slug": "test"}
        with patch.object(adapter, "_request_json", return_value=mock_data):
            spec = DashboardSpec(title="Test Dashboard")
            result = adapter.create_dashboard(spec)
        assert result.id == "new123"

    def test_create_chart_requires_dashboard_id(self):
        adapter = make_adapter()
        spec = ChartSpec(chart_type="bar", title="Test")
        with pytest.raises(DatusBiException, match="dashboard_id"):
            adapter.create_chart(spec)

    def test_create_chart_with_dashboard_id(self):
        adapter = make_adapter()
        get_mock = {
            "dashboard": {
                "title": "Test",
                "panels": [],
                "schemaVersion": 38,
                "version": 1,
            }
        }
        post_mock = {"uid": "abc", "id": 1}
        call_count = [0]

        def mock_request(method, path, **kwargs):
            call_count[0] += 1
            if method == "GET":
                return get_mock
            return post_mock

        with patch.object(adapter, "_request_json", side_effect=mock_request):
            spec = ChartSpec(chart_type="bar", title="My Chart")
            result = adapter.create_chart(spec, dashboard_id="abc123")
        assert result.name == "My Chart"
        assert call_count[0] == 2  # GET then POST

    def test_create_chart_packs_half_width_panel_next_to_existing_panel(self):
        adapter = make_adapter()
        posted = {}
        get_mock = {
            "dashboard": {
                "title": "Test",
                "panels": [
                    {
                        "id": 1,
                        "title": "Existing",
                        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
                    }
                ],
                "schemaVersion": 38,
                "version": 1,
            }
        }

        def mock_request(method, path, **kwargs):
            if method == "GET":
                return get_mock
            posted.update(kwargs["json"]["dashboard"])
            return {"uid": "abc", "id": 1}

        with patch.object(adapter, "_request_json", side_effect=mock_request):
            result = adapter.create_chart(
                ChartSpec(chart_type="bar", title="New Chart"), dashboard_id="abc123"
            )

        assert result.name == "New Chart"
        new_panel = posted["panels"][-1]
        assert new_panel["gridPos"] == {"h": 8, "w": 12, "x": 12, "y": 0}

    def test_create_big_number_uses_compact_kpi_size(self):
        adapter = make_adapter()
        posted = {}
        get_mock = {
            "dashboard": {
                "title": "Test",
                "panels": [],
                "schemaVersion": 38,
                "version": 1,
            }
        }

        def mock_request(method, path, **kwargs):
            if method == "GET":
                return get_mock
            posted.update(kwargs["json"]["dashboard"])
            return {"uid": "abc", "id": 1}

        with patch.object(adapter, "_request_json", side_effect=mock_request):
            adapter.create_chart(
                ChartSpec(chart_type="big_number", title="Total Revenue"),
                dashboard_id="abc123",
            )

        new_panel = posted["panels"][-1]
        assert new_panel["gridPos"] == {"h": 5, "w": 6, "x": 0, "y": 0}

    def test_parse_dashboard_id_from_url(self):
        adapter = make_adapter()
        uid = adapter.parse_dashboard_id("http://grafana:3000/d/abc123/my-dashboard")
        assert uid == "abc123"

    def test_parse_dashboard_id_plain(self):
        adapter = make_adapter()
        uid = adapter.parse_dashboard_id("abc123")
        assert uid == "abc123"

    def test_delete_dashboard_success(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", return_value={}):
            result = adapter.delete_dashboard("abc123")
        assert result is True

    def test_delete_dashboard_failure(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", side_effect=Exception("not found")):
            result = adapter.delete_dashboard("abc123")
        assert result is False


class TestGrafanaErrorPaths:
    def test_get_chart_without_dashboard_id_raises(self):
        adapter = make_adapter()
        with pytest.raises(DatusBiException, match="dashboard_id"):
            adapter.get_chart("panel1")

    def test_update_chart_raises(self):
        adapter = make_adapter()
        spec = ChartSpec(chart_type="bar", title="Test")
        with pytest.raises(DatusBiException, match="dashboard_id"):
            adapter.update_chart("panel1", spec)

    def test_delete_chart_returns_false(self):
        adapter = make_adapter()
        result = adapter.delete_chart("panel1")
        assert result is False

    def test_get_chart_found(self):
        adapter = make_adapter()
        mock_data = {
            "dashboard": {
                "panels": [
                    {"id": 1, "title": "Panel 1", "type": "timeseries"},
                    {"id": 2, "title": "Panel 2", "type": "barchart"},
                ]
            },
        }
        with patch.object(adapter, "_request_json", return_value=mock_data):
            chart = adapter.get_chart(1, dashboard_id="dash1")
        assert chart is not None
        assert chart.id == 1
        assert chart.name == "Panel 1"

    def test_get_chart_not_found(self):
        adapter = make_adapter()
        mock_data = {
            "dashboard": {
                "panels": [{"id": 1, "title": "Panel 1", "type": "timeseries"}]
            },
        }
        with patch.object(adapter, "_request_json", return_value=mock_data):
            chart = adapter.get_chart(999, dashboard_id="dash1")
        assert chart is None

    def test_list_datasets(self):
        adapter = make_adapter()
        mock_data = [
            {"id": 1, "name": "PostgreSQL", "type": "postgres", "typeLogoUrl": "url"},
            {"id": 2, "name": "MySQL", "type": "mysql", "typeLogoUrl": "url2"},
        ]
        with patch.object(adapter, "_request_json", return_value=mock_data):
            page = adapter.list_datasets(dashboard_id="any")
        assert page.total == 2
        assert len(page.items) == 2
        assert page.items[0].id == 1
        assert page.items[0].name == "PostgreSQL"
        assert page.items[1].id == 2

    def test_get_dataset(self):
        adapter = make_adapter()
        mock_data = {"id": 1, "name": "PostgreSQL", "type": "postgres"}
        with patch.object(adapter, "_request_json", return_value=mock_data):
            ds = adapter.get_dataset(1)
        assert ds is not None
        assert ds.id == 1
        assert ds.name == "PostgreSQL"

    def test_get_dataset_failure_returns_none(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", side_effect=Exception("fail")):
            ds = adapter.get_dataset(999)
        assert ds is None
