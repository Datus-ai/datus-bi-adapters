import pytest
from unittest.mock import patch

from datus_bi_core import DatusBiException
from datus_bi_core.models import AuthParam, ChartSpec, DashboardSpec
from datus_bi_grafana.adaptor import GrafanaAdaptor


def make_adaptor():
    auth = AuthParam(api_key="test-api-key")
    return GrafanaAdaptor(
        api_base_url="http://localhost:3000", auth_params=auth, dialect="postgres"
    )


class TestGrafanaReadOperations:
    def test_get_dashboard_info(self):
        adaptor = make_adaptor()
        mock_data = {
            "dashboard": {
                "title": "My Dashboard",
                "panels": [{"id": 1, "title": "Panel 1"}],
                "description": "",
            },
            "meta": {},
        }
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            result = adaptor.get_dashboard_info("abc123")
        assert result.name == "My Dashboard"
        assert 1 in result.chart_ids

    def test_list_charts(self):
        adaptor = make_adaptor()
        mock_data = {
            "dashboard": {
                "panels": [{"id": 1, "title": "Panel 1", "type": "timeseries"}]
            },
        }
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            charts = adaptor.list_charts("abc123")
        assert len(charts) == 1
        assert charts[0].chart_type == "timeseries"

    def test_list_dashboards(self):
        adaptor = make_adaptor()
        mock_data = [{"uid": "abc", "title": "My Dashboard"}]
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            results = adaptor.list_dashboards(search="My")
        assert len(results) == 1
        assert results[0].id == "abc"


class TestGrafanaWriteOperations:
    def test_create_dashboard(self):
        adaptor = make_adaptor()
        mock_data = {"uid": "new123", "url": "/d/new123/test", "slug": "test"}
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            spec = DashboardSpec(title="Test Dashboard")
            result = adaptor.create_dashboard(spec)
        assert result.id == "new123"

    def test_create_chart_requires_dashboard_id(self):
        adaptor = make_adaptor()
        spec = ChartSpec(chart_type="bar", title="Test")
        with pytest.raises(DatusBiException, match="dashboard_id"):
            adaptor.create_chart(spec)

    def test_create_chart_with_dashboard_id(self):
        adaptor = make_adaptor()
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

        with patch.object(adaptor, "_request_json", side_effect=mock_request):
            spec = ChartSpec(chart_type="bar", title="My Chart")
            result = adaptor.create_chart(spec, dashboard_id="abc123")
        assert result.name == "My Chart"
        assert call_count[0] == 2  # GET then POST

    def test_parse_dashboard_id_from_url(self):
        adaptor = make_adaptor()
        uid = adaptor.parse_dashboard_id("http://grafana:3000/d/abc123/my-dashboard")
        assert uid == "abc123"

    def test_parse_dashboard_id_plain(self):
        adaptor = make_adaptor()
        uid = adaptor.parse_dashboard_id("abc123")
        assert uid == "abc123"

    def test_delete_dashboard_success(self):
        adaptor = make_adaptor()
        with patch.object(adaptor, "_request_json", return_value={}):
            result = adaptor.delete_dashboard("abc123")
        assert result is True

    def test_delete_dashboard_failure(self):
        adaptor = make_adaptor()
        with patch.object(adaptor, "_request_json", side_effect=Exception("not found")):
            result = adaptor.delete_dashboard("abc123")
        assert result is False
