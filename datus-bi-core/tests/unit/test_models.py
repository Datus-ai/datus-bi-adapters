from datus_bi_core.models import AuthType, ChartSpec, DashboardSpec, DatasetSpec


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


def test_auth_type():
    assert AuthType.LOGIN.value == "login"
    assert AuthType.API_KEY.value == "api_key"
