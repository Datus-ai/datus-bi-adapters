from unittest.mock import patch

import pytest

from datus_bi_core.models import AuthParam, ChartSpec, DashboardSpec, DatasetSpec
from datus_bi_superset.adaptor import SupersetAdaptor


def make_adaptor():
    auth = AuthParam(username="admin", password="admin")
    return SupersetAdaptor(
        api_base_url="http://localhost:8088", auth_params=auth, dialect="postgresql"
    )


class TestSupersetWriteOperations:
    def test_list_dashboards(self):
        adaptor = make_adaptor()
        mock_data = {
            "result": [
                {"id": 1, "dashboard_title": "Test Dashboard", "description": "A test"}
            ]
        }
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            results = adaptor.list_dashboards(search="Test")
        assert len(results) == 1
        assert results[0].id == 1
        assert results[0].name == "Test Dashboard"

    def test_create_dashboard(self):
        adaptor = make_adaptor()
        mock_data = {"result": {"id": 10, "dashboard_title": "New Dashboard"}}
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            spec = DashboardSpec(title="New Dashboard", description="Desc")
            result = adaptor.create_dashboard(spec)
        assert result.id == 10
        assert result.name == "New Dashboard"

    def test_create_chart(self):
        adaptor = make_adaptor()
        mock_data = {"result": {"id": 5, "slice_name": "My Chart"}}
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            spec = ChartSpec(
                chart_type="bar", title="My Chart", dataset_id=1, metrics=["revenue"]
            )
            result = adaptor.create_chart(spec)
        assert result.id == 5

    def test_build_form_data(self):
        adaptor = make_adaptor()
        spec = ChartSpec(
            chart_type="bar",
            title="Test",
            dataset_id=1,
            metrics=["revenue"],
            x_axis="date",
        )
        form_data = adaptor._build_form_data(spec)
        assert form_data["viz_type"] == "echarts_timeseries_bar"
        assert len(form_data["metrics"]) == 1
        assert form_data["metrics"][0]["aggregate"] == "SUM"
        assert form_data["metrics"][0]["column"]["column_name"] == "revenue"

    def test_build_form_data_big_number_uses_singular_metric(self):
        adaptor = make_adaptor()
        spec = ChartSpec(
            chart_type="big_number",
            title="Total",
            dataset_id=1,
            metrics=["revenue"],
        )
        form_data = adaptor._build_form_data(spec)
        assert form_data["viz_type"] == "big_number_total"
        # big_number uses singular "metric", not "metrics" array
        assert "metric" in form_data
        assert "metrics" not in form_data
        assert form_data["metric"]["aggregate"] == "SUM"
        assert form_data["metric"]["column"]["column_name"] == "revenue"
        assert form_data["y_axis_format"] == "SMART_NUMBER"

    @pytest.mark.parametrize(
        "chart_type,expected_viz,uses_singular_metric",
        [
            ("bar", "echarts_timeseries_bar", False),
            ("line", "echarts_timeseries_line", False),
            ("pie", "pie", False),
            ("table", "table", False),
            ("scatter", "echarts_timeseries_scatter", False),
            ("big_number", "big_number_total", True),
        ],
    )
    def test_build_form_data_all_chart_types(self, chart_type, expected_viz, uses_singular_metric):
        """Each chart type produces valid Superset params with correct metric key."""
        adaptor = make_adaptor()
        spec = ChartSpec(
            chart_type=chart_type,
            title="Test",
            dataset_id=1,
            metrics=["revenue"],
        )
        form_data = adaptor._build_form_data(spec)
        assert form_data["viz_type"] == expected_viz
        assert form_data["datasource"] == "1__table"
        if uses_singular_metric:
            assert "metric" in form_data, f"{chart_type} should use singular 'metric'"
            assert "metrics" not in form_data, f"{chart_type} should not have 'metrics' array"
            assert form_data["metric"]["expressionType"] == "SIMPLE"
        else:
            assert "metrics" in form_data, f"{chart_type} should use 'metrics' array"
            assert len(form_data["metrics"]) == 1
            assert form_data["metrics"][0]["expressionType"] == "SIMPLE"

    @pytest.mark.parametrize(
        "metric_input,expected_agg,expected_col",
        [
            ("revenue", "SUM", "revenue"),
            ("AVG(price)", "AVG", "price"),
            ("MAX(amount)", "MAX", "amount"),
            ("MIN(cost)", "MIN", "cost"),
            ("COUNT(id)", "COUNT", "id"),
            ("COUNT_DISTINCT(user_id)", "COUNT_DISTINCT", "user_id"),
        ],
    )
    def test_metric_to_adhoc_formats(self, metric_input, expected_agg, expected_col):
        """_metric_to_adhoc correctly parses all supported metric formats."""
        adaptor = make_adaptor()
        result = adaptor._metric_to_adhoc(metric_input)
        assert result["aggregate"] == expected_agg
        assert result["column"]["column_name"] == expected_col
        assert result["expressionType"] == "SIMPLE"
        assert result["label"] == f"{expected_agg}({expected_col})"

    def test_metric_to_adhoc_count_star(self):
        """COUNT(*) produces a metric without column reference."""
        adaptor = make_adaptor()
        result = adaptor._metric_to_adhoc("COUNT(*)")
        assert result["aggregate"] == "COUNT"
        assert "column" not in result
        assert result["label"] == "COUNT(*)"

    def test_list_bi_databases(self):
        adaptor = make_adaptor()
        mock_data = {"result": [{"id": 1, "database_name": "PostgreSQL"}]}
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            dbs = adaptor.list_bi_databases()
        assert len(dbs) == 1
        assert dbs[0]["name"] == "PostgreSQL"

    def test_delete_dashboard_success(self):
        adaptor = make_adaptor()
        with patch.object(adaptor, "_request_json", return_value={}):
            result = adaptor.delete_dashboard(1)
        assert result is True

    def test_delete_chart_success(self):
        adaptor = make_adaptor()
        with patch.object(adaptor, "_request_json", return_value={}):
            result = adaptor.delete_chart(1)
        assert result is True

    def test_create_dataset(self):
        adaptor = make_adaptor()
        mock_data = {"result": {"id": 42, "table_name": "my_ds"}}
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            spec = DatasetSpec(name="my_ds", sql="SELECT * FROM orders", database_id=1)
            result = adaptor.create_dataset(spec)
        assert result.id == 42
        assert result.name == "my_ds"

    def test_update_chart(self):
        adaptor = make_adaptor()
        mock_data = {"result": {"id": 5, "slice_name": "Updated Chart"}}
        with patch.object(adaptor, "_request_json", return_value=mock_data):
            spec = ChartSpec(chart_type="line", title="Updated Chart", dataset_id=1)
            result = adaptor.update_chart(5, spec)
        assert result.id == 5
        assert result.name == "Updated Chart"

    def test_parse_dashboard_id_from_url(self):
        adaptor = make_adaptor()
        result = adaptor.parse_dashboard_id(
            "http://localhost:8088/superset/dashboard/42/"
        )
        assert result == "42"

    def test_parse_dashboard_id_numeric(self):
        adaptor = make_adaptor()
        result = adaptor.parse_dashboard_id("42")
        assert result == 42
