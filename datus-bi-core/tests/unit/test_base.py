import pytest

from datus_bi_core.base import BIAdapterBase
from datus_bi_core.models import AuthParam, AuthType


class MinimalAdapter(BIAdapterBase):
    def platform_name(self) -> str:
        return "minimal"

    def auth_type(self) -> AuthType:
        return AuthType.API_KEY

    def parse_dashboard_id(self, dashboard_url: str):
        return dashboard_url

    def get_dashboard_info(self, dashboard_id):
        return None

    def list_charts(self, dashboard_id):
        return []

    def get_chart(self, chart_id, dashboard_id=None):
        return None

    def list_datasets(self, dashboard_id):
        return []

    def get_dataset(self, dataset_id, dashboard_id=None):
        return None

    def list_dashboards(self, search: str = "", page_size: int = 20):
        return []


def test_base_default_get_chart_data_is_unsupported():
    adapter = MinimalAdapter(
        api_base_url="http://localhost",
        auth_params=AuthParam(api_key="test"),
        dialect="postgresql",
    )

    with pytest.raises(NotImplementedError) as exc_info:
        adapter.get_chart_data("1")

    assert "does not support get_chart_data" in str(exc_info.value)
