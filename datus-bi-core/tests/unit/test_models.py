from datus_bi_core.models import (
    AuthType,
    ChartDataResult,
    ChartSpec,
    DashboardSpec,
    DatasetSpec,
)


def test_chart_spec_defaults():
    spec = ChartSpec(chart_type="bar", title="Test")
    assert spec.chart_type == "bar"
    assert spec.description == ""
    assert spec.metrics is None


def test_chart_spec_full():
    spec = ChartSpec(
        chart_type="line",
        title="Revenue Trend",
        dataset_id=42,
        x_axis="date",
        metrics=["revenue"],
        dimensions=["region"],
    )
    assert spec.chart_type == "line"
    assert spec.title == "Revenue Trend"
    assert spec.dataset_id == 42
    assert spec.x_axis == "date"
    assert spec.metrics == ["revenue"]
    assert spec.dimensions == ["region"]


def test_dataset_spec():
    spec = DatasetSpec(name="my_ds", sql="SELECT * FROM orders", database_id=1)
    assert spec.name == "my_ds"
    assert spec.sql == "SELECT * FROM orders"
    assert spec.database_id == 1
    assert spec.db_schema == ""


def test_dashboard_spec():
    spec = DashboardSpec(title="My Dashboard", description="Test")
    assert spec.title == "My Dashboard"
    assert spec.description == "Test"
    assert spec.extra == {}


def test_chart_data_result_defaults():
    result = ChartDataResult(chart_id=42)

    assert result.chart_id == 42
    assert result.columns == []
    assert result.rows == []
    assert result.row_count == 0
    assert result.sql is None
    assert result.extra == {}


def test_chart_data_result_full():
    result = ChartDataResult(
        chart_id="chart-1",
        columns=["ds", "orders"],
        rows=[
            {"ds": "2025-01-01", "orders": 10},
            {"ds": "2025-01-02", "orders": 12},
        ],
        row_count=2,
        sql="SELECT ds, orders FROM daily_orders",
        extra={"truncated": False},
    )

    assert result.chart_id == "chart-1"
    assert result.columns == ["ds", "orders"]
    assert result.rows[0]["orders"] == 10
    assert result.row_count == 2
    assert "daily_orders" in result.sql
    assert result.extra["truncated"] is False


def test_auth_type():
    assert AuthType.LOGIN.value == "login"
    assert AuthType.API_KEY.value == "api_key"
