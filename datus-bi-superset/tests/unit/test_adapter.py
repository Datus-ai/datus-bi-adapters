from unittest.mock import patch

import pytest

from datus_bi_core.models import (
    AuthParam,
    ChartSpec,
    ColumnInfo,
    DashboardSpec,
    DatasetInfo,
    DatasetSpec,
)
from datus_bi_superset.adapter import SupersetAdapter, SupersetAdapterError


def make_adapter():
    auth = AuthParam(username="admin", password="admin")  # noqa: S106
    return SupersetAdapter(
        api_base_url="http://localhost:8088", auth_params=auth, dialect="postgresql"
    )


def make_dataset_info():
    return DatasetInfo(
        id=1,
        name="test_dataset",
        columns=[
            ColumnInfo(name="revenue", data_type="NUMERIC"),
            ColumnInfo(name="team", data_type="VARCHAR"),
            ColumnInfo(name="stage", data_type="VARCHAR"),
            ColumnInfo(name="status", data_type="VARCHAR"),
            ColumnInfo(
                name="created_at", data_type="TIMESTAMP", extra={"is_dttm": True}
            ),
            ColumnInfo(name="amount", data_type="NUMERIC"),
        ],
    )


class TestSupersetWriteOperations:
    def test_list_dashboards(self):
        adapter = make_adapter()
        mock_data = {
            "count": 1,
            "result": [
                {"id": 1, "dashboard_title": "Test Dashboard", "description": "A test"}
            ],
        }
        with patch.object(adapter, "_request_json", return_value=mock_data):
            page = adapter.list_dashboards(search="Test")
        # Superset reports ``count`` at the top level — total passes through.
        assert page.total == 1
        assert len(page.items) == 1
        assert page.items[0].id == 1
        assert page.items[0].name == "Test Dashboard"

    def test_create_dashboard(self):
        adapter = make_adapter()
        mock_data = {"result": {"id": 10, "dashboard_title": "New Dashboard"}}
        with patch.object(adapter, "_request_json", return_value=mock_data):
            spec = DashboardSpec(title="New Dashboard", description="Desc")
            result = adapter.create_dashboard(spec)
        assert result.id == 10
        assert result.name == "New Dashboard"

    def test_create_chart(self):
        adapter = make_adapter()
        mock_data = {"result": {"id": 5, "slice_name": "My Chart"}}
        with (
            patch.object(adapter, "get_dataset", return_value=make_dataset_info()),
            patch.object(adapter, "_fetch_chart_data_blocks", return_value=[]),
            patch.object(adapter, "_request_json", return_value=mock_data),
        ):
            spec = ChartSpec(
                chart_type="bar", title="My Chart", dataset_id=1, metrics=["revenue"]
            )
            result = adapter.create_chart(spec)
        assert result.id == 5
        assert result.name == "My Chart"

    def test_build_form_data(self):
        adapter = make_adapter()
        spec = ChartSpec(
            chart_type="bar",
            title="Test",
            dataset_id=1,
            metrics=["revenue"],
            x_axis="date",
        )
        form_data = adapter._build_form_data(spec)
        assert form_data["viz_type"] == "echarts_timeseries_bar"
        assert len(form_data["metrics"]) == 1
        assert form_data["metrics"][0]["aggregate"] == "SUM"
        assert form_data["metrics"][0]["column"]["column_name"] == "revenue"

    def test_build_form_data_sets_granularity_only_for_temporal_x_axis(self):
        adapter = make_adapter()
        dataset_info = make_dataset_info()

        categorical = adapter._build_form_data(
            ChartSpec(
                chart_type="bar",
                title="By Team",
                dataset_id=1,
                metrics=["COUNT(*)"],
                x_axis="team",
            ),
            dataset_info=dataset_info,
        )
        assert categorical["x_axis"] == "team"
        assert "granularity_sqla" not in categorical

        temporal = adapter._build_form_data(
            ChartSpec(
                chart_type="line",
                title="Over Time",
                dataset_id=1,
                metrics=["COUNT(*)"],
                x_axis="created_at",
            ),
            dataset_info=dataset_info,
        )
        assert temporal["x_axis"] == "created_at"
        assert temporal["granularity_sqla"] == "created_at"

    def test_build_form_data_funnel_promotes_x_axis_to_groupby(self):
        adapter = make_adapter()
        form_data = adapter._build_form_data(
            ChartSpec(
                chart_type="funnel",
                title="Pipeline",
                dataset_id=1,
                metrics=["COUNT(*)"],
                x_axis="stage",
            ),
            dataset_info=make_dataset_info(),
        )

        assert form_data["viz_type"] == "funnel"
        assert form_data["groupby"] == ["stage"]
        assert "x_axis" not in form_data
        assert "granularity_sqla" not in form_data

    def test_build_form_data_big_number_uses_singular_metric(self):
        adapter = make_adapter()
        spec = ChartSpec(
            chart_type="big_number",
            title="Total",
            dataset_id=1,
            metrics=["revenue"],
        )
        form_data = adapter._build_form_data(spec)
        assert form_data["viz_type"] == "big_number_total"
        # big_number uses singular "metric", not "metrics" array
        assert "metric" in form_data
        assert "metrics" not in form_data
        assert form_data["metric"]["aggregate"] == "SUM"
        assert form_data["metric"]["column"]["column_name"] == "revenue"
        assert form_data["y_axis_format"] == "SMART_NUMBER"

    def test_build_form_data_pie_uses_singular_metric(self):
        adapter = make_adapter()
        spec = ChartSpec(
            chart_type="pie",
            title="Share",
            dataset_id=1,
            metrics=["COUNT(*)"],
            dimensions=["status"],
        )
        form_data = adapter._build_form_data(spec, dataset_info=make_dataset_info())
        assert form_data["viz_type"] == "pie"
        assert form_data["groupby"] == ["status"]
        assert "metric" in form_data
        assert "metrics" not in form_data
        assert form_data["metric"]["label"] == "COUNT(*)"

    @pytest.mark.parametrize(
        "chart_type,expected_viz,uses_singular_metric",
        [
            ("bar", "echarts_timeseries_bar", False),
            ("line", "echarts_timeseries_line", False),
            ("pie", "pie", True),
            ("table", "table", False),
            ("scatter", "echarts_timeseries_scatter", False),
            ("big_number", "big_number_total", True),
        ],
    )
    def test_build_form_data_all_chart_types(
        self, chart_type, expected_viz, uses_singular_metric
    ):
        """Each chart type produces valid Superset params with correct metric key."""
        adapter = make_adapter()
        spec = ChartSpec(
            chart_type=chart_type,
            title="Test",
            dataset_id=1,
            metrics=["revenue"],
        )
        form_data = adapter._build_form_data(spec)
        assert form_data["viz_type"] == expected_viz
        assert form_data["datasource"] == "1__table"
        if uses_singular_metric:
            assert "metric" in form_data, f"{chart_type} should use singular 'metric'"
            assert "metrics" not in form_data, (
                f"{chart_type} should not have 'metrics' array"
            )
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
        adapter = make_adapter()
        result = adapter._metric_to_adhoc(metric_input)
        assert result["aggregate"] == expected_agg
        assert result["column"]["column_name"] == expected_col
        assert result["expressionType"] == "SIMPLE"
        assert result["label"] == f"{expected_agg}({expected_col})"

    def test_metric_to_adhoc_count_star(self):
        """COUNT(*) produces a metric without column reference."""
        adapter = make_adapter()
        result = adapter._metric_to_adhoc("COUNT(*)")
        assert result["aggregate"] == "COUNT"
        assert "column" not in result
        assert result["label"] == "COUNT(*)"

    def test_list_bi_databases(self):
        adapter = make_adapter()
        mock_data = {"result": [{"id": 1, "database_name": "PostgreSQL"}]}
        with patch.object(adapter, "_request_json", return_value=mock_data):
            dbs = adapter.list_bi_databases()
        assert len(dbs) == 1
        assert dbs[0]["name"] == "PostgreSQL"

    def test_delete_dashboard_success(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", return_value={}):
            result = adapter.delete_dashboard(1)
        assert result is True

    def test_delete_chart_success(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", return_value={}):
            result = adapter.delete_chart(1)
        assert result is True

    def test_create_dataset(self):
        adapter = make_adapter()
        mock_data = {"result": {"id": 42, "table_name": "my_ds"}}
        with patch.object(adapter, "_request_json", return_value=mock_data):
            spec = DatasetSpec(name="my_ds", sql="SELECT * FROM orders", database_id=1)
            result = adapter.create_dataset(spec)
        assert result.id == 42
        assert result.name == "my_ds"

    def test_create_chart_rejects_invalid_big_number_shape(self):
        adapter = make_adapter()
        spec = ChartSpec(
            chart_type="big_number",
            title="Total",
            dataset_id=1,
            metrics=["COUNT(*)"],
            dimensions=["status"],
        )

        with (
            patch.object(adapter, "get_dataset", return_value=make_dataset_info()),
            patch.object(adapter, "_request_json") as mock_request,
        ):
            with pytest.raises(
                SupersetAdapterError, match="big_number charts do not support"
            ):
                adapter.create_chart(spec)

        mock_request.assert_not_called()

    def test_create_chart_preflight_failure_blocks_chart_creation(self):
        adapter = make_adapter()
        spec = ChartSpec(
            chart_type="bar",
            title="By Team",
            dataset_id=1,
            metrics=["COUNT(*)"],
            x_axis="team",
        )

        with (
            patch.object(adapter, "get_dataset", return_value=make_dataset_info()),
            patch.object(
                adapter,
                "_fetch_chart_data_blocks",
                side_effect=SupersetAdapterError("chart/data failed for preview"),
            ),
            patch.object(adapter, "_request_json") as mock_request,
        ):
            with pytest.raises(
                SupersetAdapterError, match="chart/data failed for preview"
            ):
                adapter.create_chart(spec)

        mock_request.assert_not_called()

    def test_update_chart(self):
        adapter = make_adapter()
        existing_chart = {
            "result": {
                "id": 5,
                "slice_name": "Updated Chart",
                "datasource_id": 1,
                "datasource_type": "table",
                "params": '{"datasource": "1__table", "viz_type": "echarts_timeseries_line", "metrics": [{"aggregate": "SUM", "column": {"column_name": "amount"}, "expressionType": "SIMPLE", "label": "SUM(amount)"}], "x_axis": "created_at", "granularity_sqla": "created_at"}',
            }
        }
        update_response = {"result": {"id": 5, "slice_name": "Updated Chart"}}
        with (
            patch.object(adapter, "get_dataset", return_value=make_dataset_info()),
            patch.object(adapter, "_fetch_chart_data_blocks", return_value=[]),
            patch.object(
                adapter,
                "_request_json",
                side_effect=[existing_chart, update_response],
            ),
        ):
            spec = ChartSpec(chart_type="line", title="Updated Chart", dataset_id=1)
            result = adapter.update_chart(5, spec)
        assert result.id == 5
        assert result.name == "Updated Chart"

    def test_update_chart_uses_existing_dataset_for_preflight(self):
        adapter = make_adapter()
        spec = ChartSpec(
            chart_type="funnel",
            title="Updated Funnel",
            metrics=["COUNT(*)"],
            x_axis="stage",
        )
        existing_chart = {
            "result": {
                "id": 5,
                "slice_name": "Old Funnel",
                "datasource_id": 1,
                "datasource_type": "table",
                "params": '{"datasource": "1__table", "viz_type": "funnel"}',
            }
        }

        with (
            patch.object(adapter, "get_dataset", return_value=make_dataset_info()),
            patch.object(
                adapter,
                "_fetch_chart_data_blocks",
                side_effect=SupersetAdapterError("preview failed"),
            ),
            patch.object(
                adapter, "_request_json", side_effect=[existing_chart]
            ) as mock_request,
        ):
            with pytest.raises(SupersetAdapterError, match="preview failed"):
                adapter.update_chart(5, spec)

        assert mock_request.call_count == 1
        method, endpoint = mock_request.call_args.args[:2]
        assert method == "GET"
        assert endpoint == "explore/?slice_id=5"

    def test_parse_dashboard_id_from_url(self):
        adapter = make_adapter()
        result = adapter.parse_dashboard_id(
            "http://localhost:8088/superset/dashboard/42/"
        )
        assert result == "42"

    def test_parse_dashboard_id_numeric(self):
        adapter = make_adapter()
        result = adapter.parse_dashboard_id("42")
        assert result == 42


class TestSupersetErrorPaths:
    def test_get_dashboard_base_info_not_found(self):
        adapter = make_adapter()
        with patch.object(adapter, "get_dashboard_info", return_value=None):
            with pytest.raises(Exception, match="not found"):
                adapter.get_dashboard_base_info(
                    "http://localhost:8088/superset/dashboard/999/"
                )

    def test_delete_dashboard_failure(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", side_effect=Exception("fail")):
            result = adapter.delete_dashboard(999)
        assert result is False

    def test_delete_chart_failure(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", side_effect=Exception("fail")):
            result = adapter.delete_chart(999)
        assert result is False

    def test_delete_dataset_failure(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", side_effect=Exception("fail")):
            result = adapter.delete_dataset(999)
        assert result is False

    def test_list_dashboards_failure_returns_empty(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", side_effect=Exception("fail")):
            page = adapter.list_dashboards()
        # On error the adapter still returns the envelope shape so callers
        # don't have to branch on ``None``.
        assert page.items == []
        assert page.total is None

    def test_list_bi_databases_failure_returns_empty(self):
        adapter = make_adapter()
        with patch.object(adapter, "_request_json", side_effect=Exception("fail")):
            dbs = adapter.list_bi_databases()
        assert dbs == []


class TestParseDashboardIdEdgeCases:
    """Tests for parse_dashboard_id — covers #4 route-name bug."""

    def test_url_without_trailing_id_does_not_return_route_name(self):
        adapter = make_adapter()
        # URL with no actual ID should not return "dashboard" as the ID
        result = adapter.parse_dashboard_id("http://localhost:8088/superset/dashboard/")
        # Should return the full stripped URL, not a route segment
        assert result not in ("dashboard", "superset")

    def test_url_with_slug_after_dashboard(self):
        adapter = make_adapter()
        result = adapter.parse_dashboard_id(
            "http://localhost:8088/superset/dashboard/my-sales-dash/"
        )
        assert result == "my-sales-dash"

    def test_url_with_numeric_id(self):
        adapter = make_adapter()
        result = adapter.parse_dashboard_id(
            "http://localhost:8088/superset/dashboard/42/"
        )
        assert result == "42"

    def test_url_with_query_param_fallback(self):
        adapter = make_adapter()
        result = adapter.parse_dashboard_id(
            "http://localhost:8088/superset/dashboard/?dashboard_id=99"
        )
        assert result == "99"

    def test_empty_string(self):
        adapter = make_adapter()
        result = adapter.parse_dashboard_id("")
        assert result == ""


class TestDatasetCacheInvalidation:
    """Tests for #8 — _dataset_cache cleared on update/delete."""

    def test_update_dataset_clears_cache(self):
        adapter = make_adapter()
        # Seed cache
        adapter._dataset_cache["42"] = "cached_value"
        mock_data = {"result": {"id": 42, "table_name": "updated"}}
        with patch.object(adapter, "_request_json", return_value=mock_data):
            adapter.update_dataset(
                42, DatasetSpec(name="updated", sql="SELECT 1", database_id=1)
            )
        assert "42" not in adapter._dataset_cache

    def test_delete_dataset_clears_cache(self):
        adapter = make_adapter()
        adapter._dataset_cache["42"] = "cached_value"
        with patch.object(adapter, "_request_json", return_value={}):
            adapter.delete_dataset(42)
        assert "42" not in adapter._dataset_cache


class TestAddChartToDashboardIdempotent:
    """Tests for #7 — add_chart_to_dashboard is idempotent."""

    def test_adding_same_chart_twice_is_idempotent(self):
        adapter = make_adapter()
        position_with_chart = {
            "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
            "GRID_ID": {
                "type": "GRID",
                "id": "GRID_ID",
                "children": ["ROW-abc"],
                "parents": ["ROOT_ID"],
            },
            "ROW-abc": {
                "type": "ROW",
                "id": "ROW-abc",
                "children": ["CHART-5"],
                "parents": ["ROOT_ID", "GRID_ID"],
            },
            "CHART-5": {
                "type": "CHART",
                "id": "CHART-5",
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", "ROW-abc"],
            },
        }
        import json

        mock_dash = {"result": {"position_data": json.dumps(position_with_chart)}}
        with patch.object(adapter, "_request_json", return_value=mock_dash) as mock_req:
            result = adapter.add_chart_to_dashboard(1, 5)
        assert result is True
        # Should NOT have called PUT since chart is already present
        for call in mock_req.call_args_list:
            assert call[0][0] != "PUT"


class TestChartSpecDatasetIdType:
    """Tests for #11 — dataset_id accepts both int and str."""

    def test_dataset_id_accepts_string(self):
        spec = ChartSpec(chart_type="bar", title="Test", dataset_id="grafana-uid-123")
        assert spec.dataset_id == "grafana-uid-123"

    def test_dataset_id_accepts_int(self):
        spec = ChartSpec(chart_type="bar", title="Test", dataset_id=42)
        assert spec.dataset_id == 42
